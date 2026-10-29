"""Políticas operativas con reloj fijo y bases exclusivamente de pruebas."""

from datetime import datetime, timedelta
from io import StringIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.http import Http404
from django.test import TestCase, override_settings
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from apps.jornadas.horario import periodo_operativo
from apps.jornadas.models import AlmuerzoJornada, JornadaRepartidor
from apps.jornadas.selectores import estado_jornada_propia
from apps.jornadas.servicios import cambiar_almuerzo, finalizar_jornada, iniciar_jornada
from apps.jornadas.tests import test_jornadas as datos
from apps.repartidores.capacidad import puede_recibir_solicitudes
from apps.repartidores.selectores import listar_repartidores_autorizados, listar_repartidores_disponibles
from apps.repartidores.servicios import actualizar_operacion_repartidor
from apps.solicitudes.contingencias import procesar_cierre_diario
from apps.solicitudes.models import AsignacionSolicitud, Solicitud
from apps.solicitudes.opciones import ESTADOS_SOLICITUD_ACTIVOS
from apps.solicitudes.servicios import asignar_solicitud_manualmente
from apps.usuarios.models import Rol, RolUsuario


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL", TIME_ZONE="America/Tegucigalpa")
class PruebasHorarioAlmuerzo(TestCase):
    setUpTestData = classmethod(datos.PruebasJornadas.setUpTestData.__func__)

    def setUp(self):
        self.ahora = datetime(2026, 10, 29, 12, tzinfo=ZoneInfo("America/Tegucigalpa"))
        reloj = patch("django.utils.timezone.now", return_value=self.ahora)
        self.reloj = reloj.start()
        self.addCleanup(reloj.stop)
        self.repartidor = self.repartidores[0]
        self.usuario = self.repartidor.usuario
        self.cliente = APIClient()
        self.cliente.force_authenticate(self.usuario)

    def _iniciar(self):
        return iniciar_jornada(self.usuario, {})

    def _solicitud(self, estado="PENDING"):
        return Solicitud.objects.create(
            numero=f"ALMUERZO-{Solicitud.objects.count()}", empresa=self.empresa,
            solicitada_por=self.administrador, origen=self.origen, destino=self.destino,
            prioridad="NORMAL", cantidad_tubos=1, estado=estado,
            repartidor_asignado=self.repartidor if estado != "PENDING" else None,
        )

    def _red(self):
        self.repartidor.vehiculo.empresa = None
        self.repartidor.vehiculo.save()
        self.repartidor.empresa = None
        self.repartidor.save()
        self.usuario.empresa = None
        self.usuario.save()
        RolUsuario.objetos.filter(usuario=self.usuario).delete()
        RolUsuario.objetos.create(usuario=self.usuario, rol=Rol.objetos.get(codigo="REPARTIDOR_RED"), tipo_alcance="GLOBAL")

    def test_fecha_y_corte_salen_del_servidor(self):
        jornada = self._iniciar()
        self.assertEqual(jornada.iniciada_en, self.ahora)
        self.assertEqual(jornada.fecha_operativa, self.ahora.date())
        self.assertEqual(jornada.cierre_programado_en, self.ahora.replace(hour=22))

    def test_no_permite_segunda_jornada_aunque_se_cierre_la_primera(self):
        jornada = self._iniciar()
        finalizar_jornada(self.usuario, jornada.pk, {})
        with self.assertRaises(ValidationError) as error:
            self._iniciar()
        self.assertIn("jornada", error.exception.detail)
        self.assertEqual(JornadaRepartidor.objects.filter(repartidor=self.repartidor).count(), 1)

    def test_bloqueo_diario_tambien_cubre_historial_sin_fecha_operativa(self):
        jornada = self._iniciar()
        finalizar_jornada(self.usuario, jornada.pk, {})
        JornadaRepartidor.objects.filter(pk=jornada.pk).update(fecha_operativa=None, cierre_programado_en=None)
        with self.assertRaises(ValidationError):
            self._iniciar()

    def test_base_impide_dos_jornadas_del_mismo_dia(self):
        jornada = self._iniciar()
        finalizar_jornada(self.usuario, jornada.pk, {})
        with self.assertRaises(IntegrityError), transaction.atomic():
            JornadaRepartidor.objects.create(repartidor=self.repartidor, iniciada_en=self.ahora)

    def test_22_exactas_y_horas_posteriores_rechazan_inicio(self):
        for hora in (22, 23):
            self.reloj.return_value = self.ahora.replace(hour=hora)
            with self.subTest(hora=hora), self.assertRaises(ValidationError):
                self._iniciar()
        self.assertFalse(JornadaRepartidor.objects.exists())

    def test_antes_del_corte_permite_iniciar(self):
        self.reloj.return_value = self.ahora.replace(hour=21, minute=59, second=59)
        self.assertEqual(self._iniciar().estado, "ACTIVA")

    def test_dia_siguiente_recupera_cierre_atrasado_y_permite_una_nueva(self):
        anterior = self._iniciar()
        self.reloj.return_value = self.ahora + timedelta(days=1)
        nueva = self._iniciar()
        anterior.refresh_from_db()
        self.assertEqual(anterior.finalizada_en, self.ahora.replace(hour=22))
        self.assertEqual(nueva.fecha_operativa, self.reloj.return_value.date())
        self.assertEqual(JornadaRepartidor.objects.filter(repartidor=self.repartidor).count(), 2)

    def test_recuperacion_no_se_revierte_al_rechazar_reinicio_despues_de_22(self):
        anterior = self._iniciar()
        self.reloj.return_value = self.ahora.replace(hour=23)
        with self.assertRaises(ValidationError):
            self._iniciar()
        anterior.refresh_from_db()
        self.assertEqual(anterior.estado, "FINALIZADA")

    def test_almuerzo_pausa_excluye_asignacion_y_registra_inicio(self):
        jornada = self._iniciar()
        cambiar_almuerzo(self.usuario, jornada.pk, iniciar=True)
        self.repartidor.refresh_from_db()
        self.assertEqual(self.repartidor.estado_operativo, "PAUSED")
        self.assertFalse(puede_recibir_solicitudes(self.repartidor))
        self.assertFalse(listar_repartidores_disponibles(self.administrador).filter(pk=self.repartidor.pk).exists())
        self.assertEqual(AlmuerzoJornada.objects.get(jornada=jornada).iniciada_en, self.ahora)
        solicitud = self._solicitud()
        with self.assertRaises(ValidationError) as error:
            asignar_solicitud_manualmente(self.administrador, solicitud.pk, {"repartidor_id": self.repartidor.pk})
        self.assertIn("repartidor_id", error.exception.detail)

    def test_todos_los_estados_activos_y_pendiente_asignada_impiden_almuerzo(self):
        jornada = self._iniciar()
        for estado in ("PENDING", *ESTADOS_SOLICITUD_ACTIVOS):
            solicitud = self._solicitud(estado)
            solicitud.repartidor_asignado = self.repartidor
            solicitud.save()
            with self.subTest(estado=estado), self.assertRaises(ValidationError) as error:
                cambiar_almuerzo(self.usuario, jornada.pk, iniciar=True)
            self.assertIn("almuerzo", error.exception.detail)
            solicitud.estado = "CANCELLED"
            solicitud.save()
        self.assertFalse(AlmuerzoJornada.objects.exists())

    def test_asignacion_activa_inconsistente_tambien_impide_almuerzo(self):
        jornada = self._iniciar()
        solicitud = self._solicitud("DELIVERED")
        AsignacionSolicitud.objects.create(solicitud=solicitud, repartidor=self.repartidor, asignada_por=self.administrador)
        with self.assertRaises(ValidationError):
            cambiar_almuerzo(self.usuario, jornada.pk, iniciar=True)

    def test_solicitud_pendiente_sin_asignar_no_impide_almuerzo(self):
        jornada = self._iniciar()
        self._solicitud()
        cambiar_almuerzo(self.usuario, jornada.pk, iniciar=True)
        self.assertTrue(AlmuerzoJornada.objects.filter(finalizada_en__isnull=True).exists())

    def test_regreso_reutiliza_jornada_y_reactiva_busqueda_de_pendientes(self):
        jornada = self._iniciar()
        cambiar_almuerzo(self.usuario, jornada.pk, iniciar=True)
        regreso = self.ahora + timedelta(minutes=45)
        self.reloj.return_value = regreso
        with patch("apps.solicitudes.servicios.programar_reintento_pendientes") as reintentar:
            cambiar_almuerzo(self.usuario, jornada.pk, iniciar=False)
        reintentar.assert_called_once_with(self.empresa.pk)
        self.repartidor.refresh_from_db()
        almuerzo = AlmuerzoJornada.objects.get()
        self.assertEqual((self.repartidor.estado_operativo, almuerzo.motivo_cierre), ("AVAILABLE", "REGRESO"))
        self.assertEqual(almuerzo.finalizada_en, regreso)
        self.assertEqual(almuerzo.finalizada_por_id, self.usuario.pk)
        self.assertEqual(JornadaRepartidor.objects.count(), 1)

    def test_patch_operativo_no_puede_saltar_el_regreso_del_almuerzo(self):
        jornada = self._iniciar()
        cambiar_almuerzo(self.usuario, jornada.pk, iniciar=True)
        for actor in (self.usuario, self.administrador):
            with self.subTest(actor=actor.pk), self.assertRaises(ValidationError):
                actualizar_operacion_repartidor(actor, self.repartidor.pk, {"estado_operativo": "AVAILABLE"})
        self.assertTrue(AlmuerzoJornada.objects.filter(finalizada_en__isnull=True).exists())

    def test_desconexion_administrativa_cierra_almuerzo_con_trazabilidad(self):
        jornada = self._iniciar()
        cambiar_almuerzo(self.usuario, jornada.pk, iniciar=True)
        actualizar_operacion_repartidor(self.administrador, self.repartidor.pk, {"estado_operativo": "OUT_OF_SERVICE"})
        almuerzo = AlmuerzoJornada.objects.get()
        self.assertEqual((almuerzo.motivo_cierre, almuerzo.finalizada_por_id), ("CAMBIO_ESTADO", self.administrador.pk))

    def test_almuerzo_repetido_y_regreso_sin_inicio_son_errores_de_campo(self):
        jornada = self._iniciar()
        with self.assertRaises(ValidationError):
            cambiar_almuerzo(self.usuario, jornada.pk, iniciar=False)
        cambiar_almuerzo(self.usuario, jornada.pk, iniciar=True)
        with self.assertRaises(ValidationError):
            cambiar_almuerzo(self.usuario, jornada.pk, iniciar=True)

    def test_no_puede_operar_almuerzo_de_otro_motorista(self):
        jornada = self._iniciar()
        with self.assertRaises(Http404):
            cambiar_almuerzo(self.repartidores[1].usuario, jornada.pk, iniciar=True)
        with self.assertRaises(Http404):
            cambiar_almuerzo(self.administrador, jornada.pk, iniciar=True)

    def test_permiso_es_obligatorio(self):
        jornada = self._iniciar()
        RolUsuario.objetos.filter(usuario=self.usuario).update(activo=False, revocado_en=self.ahora)
        with self.assertRaises(PermissionDenied):
            cambiar_almuerzo(self.usuario, jornada.pk, iniciar=True)

    def test_fallo_de_historial_revierte_inicio_de_almuerzo(self):
        jornada = self._iniciar()
        with patch("apps.repartidores.operacion.HistorialEstadoRepartidor.objects.create", side_effect=RuntimeError("Fallo sintético")):
            with self.assertRaises(RuntimeError):
                cambiar_almuerzo(self.usuario, jornada.pk, iniciar=True)
        self.assertFalse(AlmuerzoJornada.objects.exists())
        self.repartidor.refresh_from_db()
        self.assertEqual(self.repartidor.estado_operativo, "AVAILABLE")

    def test_fallo_de_historial_revierte_regreso_de_almuerzo(self):
        jornada = self._iniciar()
        cambiar_almuerzo(self.usuario, jornada.pk, iniciar=True)
        with patch("apps.repartidores.operacion.HistorialEstadoRepartidor.objects.create", side_effect=RuntimeError("Fallo sintético")):
            with self.assertRaises(RuntimeError):
                cambiar_almuerzo(self.usuario, jornada.pk, iniciar=False)
        self.assertTrue(AlmuerzoJornada.objects.filter(finalizada_en__isnull=True).exists())
        self.repartidor.refresh_from_db()
        self.assertEqual(self.repartidor.estado_operativo, "PAUSED")

    def test_filtro_almuerzo_respeta_alcance_de_empresa(self):
        from apps.organizaciones.models import Empresa
        from apps.usuarios.models import Usuario

        jornada = self._iniciar()
        cambiar_almuerzo(self.usuario, jornada.pk, iniciar=True)
        otra = Empresa.objects.create(nombre="Otra empresa", pais=self.pais)
        administrador = Usuario.objetos.create(correo="admin.otra@almuerzo.test", nombres="Admin", apellidos="Otra", empresa=otra)
        RolUsuario.objetos.create(usuario=administrador, rol=Rol.objetos.get(codigo="GERENTE_OPERACIONES"), tipo_alcance="EMPRESA", empresa=otra)
        self.assertFalse(listar_repartidores_autorizados(administrador, {"en_almuerzo": True}).exists())

    def test_cierre_manual_finaliza_almuerzo_sin_abrir_otra_jornada(self):
        jornada = self._iniciar()
        cambiar_almuerzo(self.usuario, jornada.pk, iniciar=True)
        finalizar_jornada(self.usuario, jornada.pk, {})
        self.assertEqual(AlmuerzoJornada.objects.get().motivo_cierre, "CIERRE_JORNADA")
        with self.assertRaises(ValidationError):
            self._iniciar()

    def test_admin_lista_y_filtra_motoristas_en_almuerzo(self):
        jornada = self._iniciar()
        cambiar_almuerzo(self.usuario, jornada.pk, iniciar=True)
        self.cliente.force_authenticate(self.administrador)
        respuesta = self.cliente.get("/api/v1/repartidores/?en_almuerzo=true")
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data["conteo"], 1)
        self.assertTrue(respuesta.data["resultados"][0]["en_almuerzo"])
        self.assertIsNotNone(respuesta.data["resultados"][0]["almuerzo_iniciado_en"])
        self.assertEqual(listar_repartidores_autorizados(self.administrador, {"en_almuerzo": False}).count(), 1)

    def test_cierre_del_dia_finaliza_almuerzo_a_22_aunque_se_ejecute_tarde(self):
        jornada = self._iniciar()
        cambiar_almuerzo(self.usuario, jornada.pk, iniciar=True)
        self.reloj.return_value = self.ahora + timedelta(days=2)
        resultado = procesar_cierre_diario()
        jornada.refresh_from_db()
        almuerzo = AlmuerzoJornada.objects.get()
        self.assertEqual(resultado["jornadas_cerradas"], 1)
        self.assertEqual(jornada.finalizada_en, self.ahora.replace(hour=22))
        self.assertEqual(almuerzo.finalizada_en, jornada.finalizada_en)
        self.assertEqual(almuerzo.motivo_cierre, "CIERRE_JORNADA")
        self.assertEqual(procesar_cierre_diario()["jornadas_cerradas"], 0)

    def test_cierre_a_22_falla_servicios_antes_y_despues_de_recoleccion(self):
        self._iniciar()
        antes = self._solicitud("ASSIGNED")
        despues = self._solicitud("IN_TRANSIT")
        for solicitud in (antes, despues):
            AsignacionSolicitud.objects.create(solicitud=solicitud, repartidor=self.repartidor, asignada_por=self.administrador)
        corte = self.ahora.replace(hour=22)
        self.assertEqual(procesar_cierre_diario(corte - timedelta(microseconds=1))["solicitudes_cerradas"], 0)
        self.assertEqual(procesar_cierre_diario(corte)["solicitudes_cerradas"], 2)
        antes.refresh_from_db(); despues.refresh_from_db()
        self.assertEqual((antes.estado, despues.estado), ("PICKUP_FAILED", "DELIVERY_FAILED"))
        self.assertEqual((antes.cerrada_en, despues.cerrada_en), (corte, corte))

    def test_get_jornada_es_solo_lectura_y_expone_fecha_y_corte(self):
        jornada = self._iniciar()
        self.reloj.return_value = self.ahora.replace(hour=23)
        respuesta = self.cliente.get("/api/v1/jornadas/activa/")
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.data["cierre_pendiente"])
        self.assertFalse(respuesta.data["puede_iniciar_jornada"])
        self.assertFalse(respuesta.data["jornada"]["puede_operar"])
        jornada.refresh_from_db()
        self.assertEqual(jornada.estado, "ACTIVA")

    def test_apis_almuerzo_no_admiten_hora_del_telefono(self):
        jornada = self._iniciar()
        ruta = f"/api/v1/jornadas/{jornada.pk}/almuerzo/"
        respuesta = self.cliente.post(ruta + "iniciar/", {"iniciada_en": "2030-01-01T12:00:00Z"}, format="json")
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("iniciada_en", respuesta.data)
        self.assertEqual(self.cliente.post(ruta + "iniciar/", {}, format="json").status_code, 200)
        respuesta = self.cliente.post(ruta + "finalizar/", {}, format="json")
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data["id"], str(jornada.pk))
        self.assertEqual(respuesta.data["almuerzos"][0]["motivo_cierre"], "REGRESO")

    def test_regreso_despues_del_corte_no_reactiva(self):
        jornada = self._iniciar()
        cambiar_almuerzo(self.usuario, jornada.pk, iniciar=True)
        self.reloj.return_value = self.ahora.replace(hour=22)
        with self.assertRaises(ValidationError):
            cambiar_almuerzo(self.usuario, jornada.pk, iniciar=False)

    def test_network_usa_zona_servidor_y_corporate_la_de_empresa(self):
        with override_settings(TIME_ZONE="UTC"):
            self.assertEqual(periodo_operativo(self.ahora, self.empresa)[2].hour, 22)
            self.assertEqual(str(periodo_operativo(self.ahora, self.empresa)[2].tzinfo), "America/Tegucigalpa")
            with override_settings(MODO_APLICACION="EXTERNO"):
                self.assertEqual(str(periodo_operativo(self.ahora, self.empresa)[2].tzinfo), "UTC")

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_jornada_almuerzo_regreso_y_cierre(self):
        self._red()
        jornada = self._iniciar()
        cambiar_almuerzo(self.usuario, jornada.pk, iniciar=True)
        cambiar_almuerzo(self.usuario, jornada.pk, iniciar=False)
        self.reloj.return_value = self.ahora.replace(hour=22)
        call_command("cerrar_operaciones_vencidas", confirmar_network=True, stdout=StringIO())
        jornada.refresh_from_db()
        self.assertEqual(jornada.estado, "FINALIZADA")
        self.assertEqual(jornada.finalizada_en, self.ahora.replace(hour=22))
        with self.assertRaises(ValidationError):
            self._iniciar()
