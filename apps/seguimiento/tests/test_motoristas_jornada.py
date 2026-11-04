"""Ubicación administrativa durante toda la jornada, incluso sin entregas."""

from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from apps.jornadas.models import AlmuerzoJornada, JornadaRepartidor
from apps.organizaciones.models import Empresa, Sucursal
from apps.repartidores.models import Repartidor
from apps.seguimiento.models import RegistroUbicacion
from apps.seguimiento.selectores import obtener_configuracion_gps
from apps.seguimiento.servicios import registrar_ubicaciones
from apps.seguimiento.tests import test_seguimiento as datos
from apps.solicitudes.models import Solicitud
from apps.usuarios.models import Permiso, PermisoRol, Rol, RolUsuario, Usuario


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL",
                   ANTIGUEDAD_GPS_ASIGNACION_SEGUNDOS=120, PRECISION_GPS_ASIGNACION_METROS=50,
                   TIME_ZONE="America/Tegucigalpa")
class PruebasMotoristasEnJornada(TestCase):
    setUpTestData = classmethod(datos.PruebasSeguimiento.setUpTestData.__func__)

    def setUp(self):
        self.ahora = datetime(2026, 10, 30, 12, tzinfo=ZoneInfo("America/Tegucigalpa"))
        self.enterContext(patch("django.utils.timezone.now", return_value=self.ahora))
        self.enterContext(patch("apps.rutas.proveedor_google.urlopen", side_effect=AssertionError("Sin Google real")))
        self.jornada = JornadaRepartidor.objects.create(repartidor=self.repartidor, iniciada_en=self.ahora - timedelta(hours=1))
        Repartidor.objects.filter(pk=self.repartidor.pk).update(estado_operativo="AVAILABLE")
        self.cliente = APIClient(); self.cliente.force_authenticate(self.administrador)
        self.url = reverse("seguimiento:motoristas")

    def _punto(self, *, jornada=None, repartidor=None, segundos=2, precision="8.50", **cambios):
        return RegistroUbicacion.objects.create(
            id_cliente=uuid4(), jornada=jornada or self.jornada, repartidor=repartidor or self.repartidor,
            registrada_en=self.ahora - timedelta(seconds=segundos), precision_metros=precision,
            latitud=cambios.pop("latitud", "14.075000"), longitud="-87.190000", **cambios,
        )

    def _resultado(self, **filtros):
        respuesta = self.cliente.get(self.url, filtros)
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        return respuesta.data

    def _administrador_empresa(self, empresa):
        usuario = Usuario.objetos.create(correo=f"admin-{uuid4().hex}@seguimiento.test", nombres="Admin", apellidos="Empresa", empresa=empresa)
        RolUsuario.objetos.create(usuario=usuario, rol=Rol.objetos.get(codigo="ADMINISTRADOR_CORPORATIVO"), tipo_alcance="EMPRESA", empresa=empresa)
        return usuario

    def _otro_motorista(self, empresa, indice):
        usuario = Usuario.objetos.create(correo=f"motorista-{indice}@seguimiento.test", nombres=f"Otro {indice}", apellidos="Motorista", empresa=empresa)
        repartidor = Repartidor.objects.create(pais_operacion=(empresa).pais if empresa is not None else self.pais, departamento_operacion="Francisco Morazán", usuario=usuario, empresa=empresa, estado_operativo="AVAILABLE")
        jornada = JornadaRepartidor.objects.create(repartidor=repartidor, iniciada_en=self.ahora - timedelta(minutes=10))
        return repartidor, jornada

    def test_administrador_ve_ubicacion_sin_servicios(self):
        self._punto(es_operativo=False)
        datos_salida = self._resultado()
        self.assertEqual(datos_salida["conteo"], 1)
        motorista = datos_salida["resultados"][0]
        self.assertFalse(motorista["tiene_servicios_activos"])
        self.assertEqual(motorista["solicitudes_activas"], 0)
        self.assertEqual(motorista["ubicacion"]["latitud"], "14.075000")
        self.assertFalse(motorista["ubicacion"]["es_operativo"])
        self.assertTrue(motorista["ubicacion_vigente"])
        self.assertEqual(motorista["estado_ubicacion"], "ACTUALIZADA")

    def test_post_gps_sin_servicio_se_guarda_y_aparece_en_mapa(self):
        self.cliente.force_authenticate(self.usuario_repartidor)
        datos_entrada = {"jornada_id": str(self.jornada.pk), "registros": [{
            "id_cliente": str(uuid4()), "latitud": "14.075000", "longitud": "-87.190000",
            "precision_metros": "8.50", "registrada_en": (self.ahora - timedelta(seconds=2)).isoformat(),
        }]}
        respuesta = self.cliente.post(reverse("seguimiento:registros"), datos_entrada, format="json")
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        self.assertFalse(respuesta.data["registros"][0]["es_operativo"])
        self.cliente.force_authenticate(self.administrador)
        self.assertIsNotNone(self._resultado()["resultados"][0]["ubicacion"])

    def test_puntos_sin_servicio_no_se_convierten_en_km_operativos(self):
        from apps.jornadas.kilometraje import calcular_kilometraje_operativo
        registrar_ubicaciones(self.usuario_repartidor, {"jornada_id": self.jornada.pk, "registros": [
            {"id_cliente": uuid4(), "latitud": "14.075000", "longitud": "-87.190000", "precision_metros": "8.50", "registrada_en": self.ahora - timedelta(seconds=15)},
            {"id_cliente": uuid4(), "latitud": "14.075100", "longitud": "-87.190000", "precision_metros": "8.50", "registrada_en": self.ahora - timedelta(seconds=5)},
        ]})
        self.assertEqual(calcular_kilometraje_operativo(self.jornada, self.ahora)[0], 0)
        self.assertFalse(RegistroUbicacion.objects.filter(es_operativo=True).exists())

    def test_sin_gps_no_es_error_y_no_inventa_coordenadas(self):
        motorista = self._resultado()["resultados"][0]
        self.assertIsNone(motorista["ubicacion"])
        self.assertIsNone(motorista["antiguedad_segundos"])
        self.assertEqual(motorista["estado_ubicacion"], "SIN_UBICACION")
        self.assertFalse(motorista["ubicacion_vigente"])

    def test_jornada_finalizada_no_expone_ultima_posicion(self):
        self._punto()
        JornadaRepartidor.objects.filter(pk=self.jornada.pk).update(estado="FINALIZADA", finalizada_en=self.ahora)
        self.assertEqual(self._resultado()["conteo"], 0)

    def test_jornada_vencida_no_se_expone_aunque_no_corrio_mantenimiento(self):
        self._punto()
        JornadaRepartidor.objects.filter(pk=self.jornada.pk).update(cierre_programado_en=self.ahora - timedelta(seconds=1))
        self.assertEqual(self._resultado()["conteo"], 0)
        self.jornada.refresh_from_db()
        self.assertEqual(self.jornada.estado, "ACTIVA")  # Selector/vista no cierran filas.

    def test_jornada_futura_no_se_expone(self):
        JornadaRepartidor.objects.filter(pk=self.jornada.pk).update(iniciada_en=self.ahora + timedelta(minutes=5))
        self.assertEqual(self._resultado()["conteo"], 0)

    def test_no_reutiliza_gps_de_la_jornada_anterior(self):
        anterior = JornadaRepartidor.objects.create(repartidor=self.repartidor, estado="FINALIZADA",
            iniciada_en=self.ahora - timedelta(days=1), finalizada_en=self.ahora - timedelta(hours=2))
        self._punto(jornada=anterior)
        self.assertIsNone(self._resultado()["resultados"][0]["ubicacion"])

    def test_gps_futuro_y_anterior_al_inicio_no_se_usan(self):
        self._punto(segundos=-10)
        self._punto(segundos=7200)
        self.assertIsNone(self._resultado()["resultados"][0]["ubicacion"])

    def test_gps_de_otro_motorista_no_se_asocia_por_error(self):
        otro, _ = self._otro_motorista(self.empresa, 2)
        self._punto(repartidor=otro, jornada=self.jornada)
        self.assertIsNone(self._resultado(repartidor_id=str(self.repartidor.pk))["resultados"][0]["ubicacion"])

    def test_ubicacion_antigua_se_marca_sin_presentarla_como_actual(self):
        self._punto(segundos=121)
        motorista = self._resultado()["resultados"][0]
        self.assertEqual(motorista["estado_ubicacion"], "DESACTUALIZADA")
        self.assertEqual(motorista["antiguedad_segundos"], 121)
        self.assertFalse(motorista["ubicacion_vigente"])
        self.assertIsNotNone(motorista["ubicacion"])

    def test_calidad_y_antiguedad_respetan_limites_exactos(self):
        for segundos, precision, estado in ((120, "50", "ACTUALIZADA"), (2, None, "SIN_PRECISION"), (2, "50.01", "BAJA_PRECISION")):
            with self.subTest(segundos=segundos, precision=precision):
                RegistroUbicacion.objects.all().delete()
                self._punto(segundos=segundos, precision=precision)
                self.assertEqual(self._resultado()["resultados"][0]["estado_ubicacion"], estado)

    def test_elige_ultima_captura_y_no_ultimo_lote_recibido(self):
        self._punto(segundos=2, latitud="14.076000")
        self._punto(segundos=60, latitud="14.077000")
        self.assertEqual(self._resultado()["resultados"][0]["ubicacion"]["latitud"], "14.076000")

    def test_almuerzo_y_pausa_siguen_visibles_durante_jornada(self):
        self._punto()
        Repartidor.objects.filter(pk=self.repartidor.pk).update(estado_operativo="PAUSED")
        AlmuerzoJornada.objects.create(jornada=self.jornada, iniciada_en=self.ahora - timedelta(minutes=10))
        motorista = self._resultado(en_almuerzo="true")["resultados"][0]
        self.assertTrue(motorista["en_almuerzo"])
        self.assertEqual(motorista["estado_operativo"], "PAUSED")
        self.assertFalse(motorista["tiene_servicios_activos"])

    def test_filtra_con_y_sin_servicios(self):
        self.assertEqual(self._resultado(con_servicios="false")["conteo"], 1)
        solicitud = Solicitud.objects.create(numero="ACTIVA-MAPA", empresa=self.empresa,
            solicitada_por=self.solicitante, repartidor_asignado=self.repartidor,
            prioridad="NORMAL", estado="ASSIGNED", cantidad_tubos=1, origen=self.origen, destino=self.destino)
        self.assertEqual(self._resultado(con_servicios="true")["resultados"][0]["solicitudes_activas"], 1)
        self.assertEqual(self._resultado(con_servicios="false")["conteo"], 0)
        Solicitud.objects.filter(pk=solicitud.pk).update(estado="DELIVERED")
        self.assertEqual(self._resultado(con_servicios="false")["conteo"], 1)

    def test_perfil_o_usuario_inactivo_no_se_expone(self):
        Repartidor.objects.filter(pk=self.repartidor.pk).update(activo=False)
        self.assertEqual(self._resultado()["conteo"], 0)
        Repartidor.objects.filter(pk=self.repartidor.pk).update(activo=True)
        Usuario.objetos.filter(pk=self.usuario_repartidor.pk).update(estado="SUSPENDIDO")
        self.assertEqual(self._resultado()["conteo"], 0)

    def test_solicitante_y_motorista_no_pueden_consultar_flota(self):
        for usuario in (self.solicitante, self.usuario_repartidor):
            self.cliente.force_authenticate(usuario)
            self.assertEqual(self.cliente.get(self.url).status_code, 403)

    def test_sin_autenticacion_devuelve_401(self):
        self.cliente.force_authenticate(None)
        self.assertEqual(self.cliente.get(self.url).status_code, 401)

    def test_admin_empresa_no_ve_otra_empresa(self):
        otra = Empresa.objects.create(nombre="Otra empresa", pais=self.pais)
        self._otro_motorista(otra, 2)
        self.cliente.force_authenticate(self._administrador_empresa(self.empresa))
        datos_salida = self._resultado()
        self.assertEqual(datos_salida["conteo"], 1)
        self.assertEqual(datos_salida["resultados"][0]["empresa_id"], str(self.empresa.pk))
        self.assertEqual(self._resultado(empresa_id=str(otra.pk))["conteo"], 0)

    def test_permiso_de_sucursal_no_habilita_ubicacion_de_toda_la_empresa(self):
        sucursal = Sucursal.objects.create(empresa=self.empresa, ubicacion=self.origen, nombre="Sucursal limitada")
        usuario = Usuario.objetos.create(correo="mapa.sucursal@seguimiento.test", nombres="Sucursal", apellidos="Limitada", empresa=self.empresa)
        rol = Rol.objetos.create(codigo="MAPA_SUCURSAL", nombre="Mapa sucursal", permite_alcance_sucursal=True)
        PermisoRol.objetos.create(rol=rol, permiso=Permiso.objetos.get(codigo="repartidor.ver_ubicacion"))
        RolUsuario.objetos.create(usuario=usuario, rol=rol, tipo_alcance="SUCURSAL", empresa=self.empresa, sucursal=sucursal)
        self.cliente.force_authenticate(usuario)
        self.assertEqual(self.cliente.get(self.url).status_code, 403)

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_operador_global_ve_flota_global_sin_empresa(self):
        Repartidor.objects.filter(pk=self.repartidor.pk).update(empresa=None)
        Usuario.objetos.filter(pk=self.usuario_repartidor.pk).update(empresa=None)
        operador = Usuario.objetos.create(correo="operador.mapa@seguimiento.test", nombres="Operador", apellidos="Red")
        RolUsuario.objetos.create(usuario=operador, rol=Rol.objetos.get(codigo="OPERADOR_RED"), tipo_alcance="GLOBAL")
        self.cliente.force_authenticate(operador)
        self.assertEqual(self._resultado()["resultados"][0]["empresa_id"], None)
        respuesta = self.cliente.get(self.url, {"empresa_id": str(self.empresa.pk)})
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("empresa_id", respuesta.data)

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_administrador_de_cliente_no_ve_flota_compartida(self):
        self.cliente.force_authenticate(self._administrador_empresa(self.empresa))
        self.assertEqual(self.cliente.get(self.url).status_code, 403)

    def test_filtros_invalidos_conservan_nombre_de_campo(self):
        for campo, valor in (("repartidor_id", "invalido"), ("estado_operativo", "ALMUERZO"), ("inexistente", "true")):
            with self.subTest(campo=campo):
                respuesta = self.cliente.get(self.url, {campo: valor})
                self.assertEqual(respuesta.status_code, 400)
                self.assertIn(campo, respuesta.data)

    def test_paginacion_y_consultas_no_crecen_por_cada_motorista(self):
        self._punto()
        with CaptureQueriesContext(connection) as inicial:
            self._resultado()
        for indice in range(2, 11):
            r, j = self._otro_motorista(self.empresa, indice)
            self._punto(repartidor=r, jornada=j)
        with CaptureQueriesContext(connection) as ampliado:
            datos_salida = self._resultado(tamano_pagina=5)
        self.assertEqual(datos_salida["conteo"], 10)
        self.assertEqual(len(datos_salida["resultados"]), 5)
        self.assertIsNotNone(datos_salida["pagina_siguiente"])
        self.assertLessEqual(len(ampliado), len(inicial) + 1)

    def test_datos_sin_identificadores_privados_del_dispositivo_y_sin_cache(self):
        self._punto()
        respuesta = self.cliente.get(self.url)
        self.assertEqual(respuesta["Cache-Control"], "no-store")
        ubicacion = respuesta.data["resultados"][0]["ubicacion"]
        self.assertNotIn("sesion_gps", ubicacion)
        self.assertNotIn("id_cliente", ubicacion)
        self.assertIn("recibida_en", ubicacion)
        self.assertEqual(respuesta.data["intervalo_actualizacion_segundos"], settings.INTERVALO_GPS_ENVIO_SEGUNDOS)

    def test_configuracion_exige_capturar_toda_jornada_aun_sin_servicios(self):
        configuracion = obtener_configuracion_gps(self.usuario_repartidor)
        seguimiento = configuracion["seguimiento_jornada"]
        self.assertTrue(seguimiento["captura_habilitada"])
        self.assertEqual(seguimiento["jornada_id"], str(self.jornada.pk))
        self.assertFalse(seguimiento["requiere_servicio_activo"])
        self.assertTrue(seguimiento["incluye_tiempo_sin_servicios"])
        self.assertTrue(seguimiento["incluye_almuerzo"])
        self.assertTrue(seguimiento["detener_al_finalizar_jornada"])

    def test_configuracion_deshabilita_captura_sin_jornada_vigente(self):
        JornadaRepartidor.objects.filter(pk=self.jornada.pk).update(cierre_programado_en=self.ahora)
        seguimiento = obtener_configuracion_gps(self.usuario_repartidor)["seguimiento_jornada"]
        self.assertFalse(seguimiento["captura_habilitada"])
        self.assertIsNone(seguimiento["jornada_id"])
