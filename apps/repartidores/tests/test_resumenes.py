"""Resumen administrativo diario: atribución, permisos, datos ausentes y límites."""

from datetime import date, datetime, timedelta, timezone as zona_utc
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from apps.evidencias.models import EvidenciaSolicitud
from apps.jornadas.models import JornadaRepartidor
from apps.organizaciones.models import Empresa, Sucursal
from apps.repartidores.models import Repartidor
from apps.solicitudes.models import AsignacionSolicitud, Solicitud
from apps.solicitudes.tests import test_asignaciones as datos
from apps.usuarios.models import Permiso, PermisoRol, Rol, RolUsuario, Usuario


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasResumenesMotoristas(TestCase):
    setUpTestData = classmethod(datos.PruebasAsignacionesSolicitud.setUpTestData.__func__)

    def setUp(self):
        self.repartidor = self.repartidores[0]
        self.fecha = date(2026, 10, 27)
        self.inicio = datetime(2026, 10, 27, tzinfo=ZoneInfo("America/Tegucigalpa"))
        self.fin = self.inicio + timedelta(days=1)
        self.ahora = self.inicio + timedelta(hours=12)
        self.cliente = APIClient()
        self.cliente.force_authenticate(self.administrador)
        self.enterContext(patch("apps.rutas.proveedor_google.urlopen", side_effect=AssertionError("El resumen no consulta Google.")))

    def _consultar(self, repartidor=None, **parametros):
        return self.cliente.get(reverse("repartidores:resumen", args=[(repartidor or self.repartidor).pk]),
                                {"fecha_operativa": str(self.fecha), **parametros})

    def _lista(self, **parametros):
        return self.cliente.get(reverse("repartidores:resumenes"), {"fecha_operativa": str(self.fecha), **parametros})

    def _solicitud(self, cantidad=3, *, estado="DELIVERED", repartidor=None, historial=True):
        r = repartidor or self.repartidor
        recogida = estado in ("PICKED_UP", "IN_TRANSIT", "AT_DESTINATION", "DELIVERED", "DELIVERY_FAILED")
        terminal = estado in ("DELIVERED", "DELIVERY_FAILED", "PICKUP_FAILED", "CANCELLED")
        s = Solicitud.objects.create(
            cantidad_tubos=cantidad, numero=f"RES-{uuid4().hex[:12]}", empresa=self.empresa,
            solicitada_por=self.administrador, repartidor_asignado=r, prioridad="NORMAL",
            origen=self.origen, destino=self.destino, estado=estado,
            recolectada_en=self.inicio + timedelta(hours=2) if recogida else None,
            entregada_en=self.inicio + timedelta(hours=3) if estado == "DELIVERED" else None,
            cerrada_en=self.inicio + timedelta(hours=3) if terminal else None,
        )
        if historial:
            AsignacionSolicitud.objects.create(solicitud=s, repartidor=r, asignada_por=self.administrador,
                asignada_en=self.inicio + timedelta(hours=1),
                estado=("FINALIZADA" if estado == "DELIVERED" else "CANCELADA") if terminal else "ACTIVA",
                finalizada_en=s.cerrada_en)
        return s

    def _lectura(self, valor="4.50", *, solicitud=None, capturada=None, repartidor=None):
        return EvidenciaSolicitud.objects.create(
            solicitud=solicitud or self._solicitud(), repartidor=repartidor or self.repartidor,
            tipo="FOTO_RECOLECCION", temperatura_contenedor_c=valor,
            fuente_temperatura="MANUAL" if valor is not None else None,
            capturada_en=capturada or self.inicio + timedelta(hours=2),
            clave_almacenamiento=f"pruebas/{uuid4()}.png", tipo_contenido="image/png", tamano_bytes=100,
            latitud=self.origen.latitud, longitud=self.origen.longitud,
        )

    def _jornada(self, km="1.234", *, calidad="CONSOLIDADO", disponible=True, finalizada=None):
        return JornadaRepartidor.objects.create(
            repartidor=self.repartidor, iniciada_en=self.inicio + timedelta(hours=1),
            finalizada_en=finalizada or self.inicio + timedelta(hours=4), estado="FINALIZADA",
            kilometros_operativos=km, kilometraje_disponible=disponible, calidad_kilometraje={"estado": calidad},
        )

    def _lector(self, empresa=None, *, permisos=None, sucursal=None):
        empresa = empresa or self.empresa
        usuario = Usuario.objetos.create(correo=f"lector-{uuid4().hex}@example.test", nombres="Lector", apellidos="Prueba", empresa=empresa)
        rol = Rol.objetos.create(codigo=f"LECTOR_{uuid4().hex[:8]}", nombre="Lector de prueba",
            permite_alcance_empresa=not bool(sucursal), permite_alcance_sucursal=bool(sucursal))
        for codigo in permisos if permisos is not None else ("reporte.ver", "repartidor.ver", "solicitud.ver", "jornada.ver", "evidencia.ver"):
            PermisoRol.objetos.create(rol=rol, permiso=Permiso.objetos.get(codigo=codigo))
        RolUsuario.objetos.create(usuario=usuario, rol=rol, tipo_alcance="SUCURSAL" if sucursal else "EMPRESA",
            empresa=empresa, sucursal=sucursal, asignado_por=self.administrador)
        return usuario

    def test_dia_sin_actividad_cero_contadores_y_mediciones_desconocidas(self):
        r = self._consultar()
        self.assertEqual(r.status_code, 200, r.data)
        d = r.json()
        self.assertTrue(all(v == 0 for v in d["solicitudes"].values()))
        self.assertIsNone(d["kilometraje"]["kilometros_medidos"])
        self.assertIsNone(d["temperaturas"]["promedio_c"])
        self.assertEqual(d["temperaturas"]["ultimas_lecturas"], [])
        self.assertEqual(d["carga_actual"]["limite_tubos"], 20)

    def test_dos_pedidos_con_misma_cantidad_no_deduplican_tubos(self):
        self._solicitud(3); self._solicitud(3)
        d = self._consultar().json()
        self.assertEqual(d["solicitudes"]["entregadas"], 2)
        self.assertEqual(d["solicitudes"]["recolectadas"], 2)
        self.assertEqual(d["solicitudes"]["asignadas"], 2)
        self.assertEqual(d["tubos"]["entregados_conocidos"], 6)

    def test_reasignacion_atribuye_recogida_y_entrega_a_sus_responsables(self):
        s = self._solicitud(8)
        cambio = self.inicio + timedelta(hours=2, minutes=30)
        s.asignaciones.update(estado="REASIGNADA", finalizada_en=cambio)
        otro = self.repartidores[1]
        AsignacionSolicitud.objects.create(solicitud=s, repartidor=otro, asignada_por=self.administrador,
            asignada_en=cambio, estado="FINALIZADA", finalizada_en=s.entregada_en)
        Solicitud.objects.filter(pk=s.pk).update(repartidor_asignado=otro)
        a, b = self._consultar().json(), self._consultar(otro).json()
        self.assertEqual((a["solicitudes"]["recolectadas"], a["solicitudes"]["entregadas"]), (1, 0))
        self.assertEqual((b["solicitudes"]["recolectadas"], b["solicitudes"]["entregadas"]), (0, 1))
        self.assertEqual((a["tubos"]["recogidos_conocidos"], b["tubos"]["entregados_conocidos"]), (8, 8))

    def test_cambios_en_instante_exacto_no_cuentan_recogida_dos_veces(self):
        s = self._solicitud()
        s.asignaciones.update(estado="REASIGNADA", finalizada_en=s.recolectada_en)
        otro = self.repartidores[1]
        AsignacionSolicitud.objects.create(solicitud=s, repartidor=otro, asignada_por=self.administrador,
            asignada_en=s.recolectada_en, estado="FINALIZADA", finalizada_en=s.entregada_en)
        self.assertEqual(self._consultar().json()["solicitudes"]["recolectadas"], 0)
        self.assertEqual(self._consultar(otro).json()["solicitudes"]["recolectadas"], 1)

    def test_historial_tiene_precedencia_sobre_motorista_actual(self):
        s = self._solicitud()
        otro = self.repartidores[1]
        Solicitud.objects.filter(pk=s.pk).update(repartidor_asignado=otro)
        self.assertEqual(self._consultar().json()["solicitudes"]["entregadas"], 1)
        self.assertEqual(self._consultar(otro).json()["solicitudes"]["entregadas"], 0)

    def test_historico_sin_asignaciones_utiliza_responsable_conocido(self):
        self._solicitud(historial=False)
        self.assertEqual(self._consultar().json()["solicitudes"]["entregadas"], 1)

    def test_asignaciones_repetidas_a_mismo_motorista_cuentan_un_pedido(self):
        s = self._solicitud()
        AsignacionSolicitud.objects.create(solicitud=s, repartidor=self.repartidor, asignada_por=self.administrador,
            asignada_en=self.inicio, finalizada_en=self.inicio + timedelta(minutes=30), estado="REASIGNADA")
        d = self._consultar().json()
        self.assertEqual(d["solicitudes"]["asignadas"], 1)
        self.assertEqual(d["tubos"]["entregados_conocidos"], 3)

    def test_cantidades_historicas_desconocidas_se_informan(self):
        self._solicitud(None)
        d = self._consultar().json()["tubos"]
        self.assertEqual((d["recogidos_conocidos"], d["entregados_conocidos"]), (0, 0))
        self.assertEqual((d["recolecciones_sin_cantidad"], d["entregas_sin_cantidad"]), (1, 1))

    def test_fallidas_y_canceladas_utilizan_cierre_y_no_fecha_creacion(self):
        self._solicitud(estado="PICKUP_FAILED"); self._solicitud(estado="DELIVERY_FAILED"); self._solicitud(estado="CANCELLED")
        d = self._consultar().json()["solicitudes"]
        self.assertEqual((d["fallidas"], d["canceladas"]), (2, 1))

    def test_entregas_se_filtran_por_entregada_en_con_limites_locales(self):
        s = self._solicitud(historial=False)
        Solicitud.objects.filter(pk=s.pk).update(entregada_en=self.inicio, creado_en=self.inicio - timedelta(days=10))
        fuera = self._solicitud(historial=False)
        Solicitud.objects.filter(pk=fuera.pk).update(entregada_en=self.fin)
        self.assertEqual(self._consultar().json()["solicitudes"]["entregadas"], 1)

    def test_carga_actual_no_se_presenta_como_carga_historica_del_dia(self):
        self._solicitud(18, estado="ASSIGNED")
        d = self._consultar(fecha_operativa="2026-10-26").json()
        self.assertEqual(d["solicitudes"]["asignadas"], 0)
        self.assertEqual(d["carga_actual"]["tubos_comprometidos"], 18)
        self.assertEqual(d["carga_actual"]["tubos_disponibles"], 2)

    def test_temperaturas_agrupan_sin_multiplicar_por_asignaciones(self):
        self._lectura("2.00"); self._lectura("4.00"); self._lectura(None)
        d = self._consultar().json()["temperaturas"]
        self.assertEqual((d["lecturas_registradas"], d["lecturas_con_temperatura"], d["lecturas_sin_temperatura"]), (3, 2, 1))
        self.assertEqual((d["minima_c"], d["maxima_c"], d["promedio_c"]), ("2.00", "4.00", "3.00"))

    def test_cero_grados_no_se_confunde_con_dato_ausente(self):
        self._lectura("0.00")
        self.assertEqual(self._consultar().json()["temperaturas"]["minima_c"], "0.00")

    def test_ultimas_cinco_y_lecturas_paginadas_en_el_mismo_orden(self):
        lecturas = [self._lectura(capturada=self.inicio + timedelta(hours=i)) for i in range(1, 8)]
        d = self._consultar().json()["temperaturas"]
        self.assertEqual([l["id"] for l in d["ultimas_lecturas"]], [str(l.pk) for l in reversed(lecturas[2:])])
        r = self.cliente.get(reverse("repartidores:temperaturas", args=[self.repartidor.pk]),
            {"fecha_operativa": str(self.fecha), "tamano_pagina": 2})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["conteo"], 7)
        self.assertIsNotNone(r.data["pagina_siguiente"])
        self.assertEqual([l["id"] for l in r.data["resultados"]], [str(l.pk) for l in reversed(lecturas[-2:])])
        self.assertNotIn("clave_almacenamiento", r.data["resultados"][0])

    def test_kilometros_distinguen_medidos_y_consolidados(self):
        self._jornada("12.345"); self._jornada("2.111", calidad="SIN_VERIFICAR"); self._jornada("0", disponible=False, calidad="SIN_DATOS")
        d = self._consultar().json()["kilometraje"]
        self.assertEqual((d["kilometros_medidos"], d["kilometros_consolidados"]), ("14.456", "12.345"))
        self.assertEqual((d["jornadas_cerradas"], d["jornadas_con_medicion"], d["jornadas_consolidadas"]), (3, 2, 1))
        self.assertFalse(d["completo"])

    def test_cierre_exactamente_medianoche_pertenece_al_dia_terminado(self):
        self._jornada("2.000", finalizada=self.fin)
        d = self._consultar().json()["kilometraje"]
        self.assertEqual(d["kilometros_consolidados"], "2.000")
        self.assertEqual(d["jornadas_sin_cierre_en_periodo"], 0)
        self.assertTrue(d["completo"])
        self.assertEqual(self._consultar(fecha_operativa="2026-10-28").json()["kilometraje"]["jornadas_cerradas"], 0)

    def test_jornada_abierta_no_se_suma_como_kilometraje_final(self):
        JornadaRepartidor.objects.create(repartidor=self.repartidor, iniciada_en=self.inicio, kilometros_operativos="99")
        with patch("apps.repartidores.resumenes.timezone.now", return_value=self.ahora):
            d = self._consultar().json()["kilometraje"]
        self.assertIsNone(d["kilometros_medidos"])
        self.assertEqual(d["jornadas_sin_cierre_en_periodo"], 1)

    def test_paginacion_de_motoristas_y_filtro_de_empresa(self):
        r = self._lista(tamano_pagina=1)
        self.assertEqual((r.status_code, r.data["conteo"], len(r.data["resultados"])), (200, 2, 1))
        self.assertIsNotNone(r.data["pagina_siguiente"])
        self.assertEqual(self._lista(empresa_id=str(uuid4())).data["conteo"], 0)

    def test_administrador_empresa_no_ve_motoristas_de_otra(self):
        otra = Empresa.objects.create(nombre="Otra", pais=self.empresa.pais)
        u = Usuario.objetos.create(correo="otro@example.test", nombres="Otro", apellidos="Motorista", empresa=otra)
        r = Repartidor.objects.create(usuario=u, empresa=otra)
        self.cliente.force_authenticate(self._lector())
        self.assertEqual(self._lista().data["conteo"], 2)
        self.assertEqual(self._consultar(r).status_code, 404)
        self.assertEqual(self._lista(empresa_id=str(otra.pk)).data["conteo"], 0)

    def test_solicitante_y_motorista_sin_permiso_reportes_no_acceden(self):
        for usuario in (self.repartidor.usuario, Usuario.objetos.create(correo="sin@example.test", nombres="Sin", apellidos="Permisos")):
            self.cliente.force_authenticate(usuario)
            self.assertEqual(self._lista().status_code, 403)

    def test_no_basta_reporte_ver_sin_permiso_evidencias(self):
        self.cliente.force_authenticate(self._lector(permisos=("repartidor.ver", "reporte.ver", "solicitud.ver", "jornada.ver")))
        self.assertEqual(self._lista().status_code, 403)

    def test_permiso_sucursal_no_habilita_historial_completo_del_motorista(self):
        sucursal = Sucursal.objects.create(nombre="Sucursal", empresa=self.empresa, ubicacion=self.origen)
        self.cliente.force_authenticate(self._lector(sucursal=sucursal))
        self.assertEqual(self._lista().data["conteo"], 0)
        self.assertEqual(self._consultar().status_code, 404)

    @override_settings(MODO_APLICACION="EXTERNO", TIME_ZONE="America/Tegucigalpa")
    def test_cliente_network_no_ve_resumen_global_de_otras_empresas(self):
        u = Usuario.objetos.create(correo="global@example.test", nombres="Red", apellidos="Global")
        r = Repartidor.objects.create(usuario=u)
        self.cliente.force_authenticate(self._lector())
        self.assertEqual(self._consultar(r).status_code, 404)
        self.cliente.force_authenticate(self.administrador)
        d = self._consultar(r).json()
        self.assertIsNone(d["repartidor"]["empresa_id"])
        self.assertEqual(d["zona_horaria_operativa"], "America/Tegucigalpa")

    def test_fechas_invalidas_y_filtros_desconocidos_tienen_campo_estable(self):
        for fecha in ("2026-02-30", "27/10/2026", "2026-1-7", "9999-12-31"):
            r = self._consultar(fecha_operativa=fecha)
            self.assertEqual(r.status_code, 400)
            self.assertIn("fecha_operativa", r.data)
        r = self._consultar(solicitada_por_id=str(uuid4()))
        self.assertEqual(r.status_code, 400)
        self.assertIn("solicitada_por_id", r.data)

    def test_fecha_por_defecto_depende_del_servidor_y_pais_del_motorista(self):
        with patch("apps.repartidores.resumenes.timezone.now", return_value=self.inicio + timedelta(hours=23)):
            r = self.cliente.get(reverse("repartidores:resumen", args=[self.repartidor.pk]))
        self.assertEqual(r.json()["fecha_operativa"], str(self.fecha))

    def test_dia_con_cambio_horario_usa_limites_locales_reales(self):
        pais = self.empresa.pais
        pais.zona_horaria_predeterminada = "America/New_York"; pais.save()
        d = self._consultar(fecha_operativa="2026-03-08").json()["periodo"]
        inicio = datetime.fromisoformat(d["desde"]).astimezone(zona_utc.utc)
        fin = datetime.fromisoformat(d["hasta_exclusivo"]).astimezone(zona_utc.utc)
        self.assertEqual((fin - inicio).total_seconds(), 23 * 3600)

    def test_lectura_no_escribe_ni_carga_puntos_gps(self):
        self._lectura()
        with CaptureQueriesContext(connection) as consultas:
            r = self._consultar()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(all(q["sql"].lstrip().upper().startswith("SELECT") for q in consultas))
        self.assertFalse(any('"registros_ubicacion"' in q["sql"] for q in consultas))

    def test_cantidad_consultas_no_crece_por_motorista_de_la_misma_zona(self):
        with CaptureQueriesContext(connection) as pocas:
            self.assertEqual(self._lista().status_code, 200)
        for n in range(3):
            u = Usuario.objetos.create(correo=f"extra{n}@example.test", nombres="Extra", apellidos=str(n), empresa=self.empresa)
            Repartidor.objects.create(usuario=u, empresa=self.empresa)
        with CaptureQueriesContext(connection) as varias:
            self.assertEqual(self._lista().data["conteo"], 5)
        self.assertEqual(len(pocas), len(varias))

    def test_anonimo_no_accede(self):
        self.cliente.force_authenticate(None)
        self.assertEqual(self._lista().status_code, 401)

    def test_filtro_activo_se_aplica_solo_cuando_se_envia(self):
        Repartidor.objects.filter(pk=self.repartidor.pk).update(activo=False)
        self.assertEqual(self._lista().data["conteo"], 2)
        self.assertEqual(self._lista(activo="false").data["conteo"], 1)
        self.assertEqual(self._lista(activo="true").data["conteo"], 1)
        self.assertEqual(self._consultar().status_code, 200)

    def test_repartidor_ver_de_sucursal_no_se_amplia_con_otros_permisos_de_empresa(self):
        sucursal = Sucursal.objects.create(nombre="Limitada", empresa=self.empresa, ubicacion=self.origen)
        usuario = self._lector(permisos=("repartidor.ver",), sucursal=sucursal)
        completo = self._lector(permisos=("reporte.ver", "solicitud.ver", "jornada.ver", "evidencia.ver"))
        asignacion = completo.asignaciones_roles.get()
        RolUsuario.objetos.create(usuario=usuario, rol=asignacion.rol, tipo_alcance="EMPRESA", empresa=self.empresa, asignado_por=self.administrador)
        self.cliente.force_authenticate(usuario)
        self.assertEqual(self._lista().data["conteo"], 0)
        self.assertEqual(self._consultar().status_code, 404)

    def test_temperaturas_de_otro_motorista_no_se_mezclan(self):
        self._lectura("4.50")
        self._lectura("99.00", repartidor=self.repartidores[1])
        d = self._consultar().json()["temperaturas"]
        self.assertEqual(d["lecturas_registradas"], 1)
        self.assertEqual(d["maxima_c"], "4.50")

    def test_fallida_por_fin_dia_se_atribuye_al_dia_operativo_que_termino(self):
        s = self._solicitud(estado="PICKUP_FAILED")
        Solicitud.objects.filter(pk=s.pk).update(cerrada_en=self.fin, motivo_cierre="FIN_DIA")
        s.asignaciones.update(finalizada_en=self.fin)
        self.assertEqual(self._consultar().json()["solicitudes"]["fallidas"], 1)
        self.assertEqual(self._consultar(fecha_operativa="2026-10-28").json()["solicitudes"]["fallidas"], 0)

    def test_kilometraje_de_jornada_entre_dias_se_atribuye_completo_a_su_cierre(self):
        j = self._jornada("7.000")
        JornadaRepartidor.objects.filter(pk=j.pk).update(iniciada_en=self.inicio - timedelta(hours=2))
        d = self._consultar().json()["kilometraje"]
        self.assertEqual(d["criterio"], "CIERRE_JORNADA")
        self.assertEqual(d["kilometros_consolidados"], "7.000")
        self.assertEqual(self._consultar(fecha_operativa="2026-10-26").json()["kilometraje"]["jornadas_cerradas"], 0)
