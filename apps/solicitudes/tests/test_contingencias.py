"""Traspasos corporativos y corte a las22:00, sin escribir en bases reales."""

from datetime import timedelta
from uuid import uuid4
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.http import Http404
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.jornadas.models import JornadaRepartidor
from apps.jornadas.servicios import _calcular_resumen
from apps.notificaciones.models import NotificacionUsuario
from apps.repartidores.models import Repartidor
from apps.rutas.models import RutaRepartidor
from apps.rutas.selectores import obtener_paradas_operativas
from apps.seguimiento.models import RegistroUbicacion
from apps.solicitudes.contingencias import (
    cerrar_solicitud_vencida, procesar_cierre_diario, procesar_suspension,
)
from apps.solicitudes.models import AsignacionSolicitud, EventoSolicitud, MovimientoEnvioEspecial, Solicitud
from apps.solicitudes.opciones import EstadoSolicitud
from apps.solicitudes.serializadores import SerializadorSolicitudDetalle
from apps.solicitudes.servicios import asignar_solicitud_manualmente, cambiar_estado_solicitud, reintentar_solicitudes_pendientes
from apps.solicitudes.servicios_movimientos import confirmar_sincronizacion_movimiento, iniciar_movimiento_especial
from apps.solicitudes.tests import test_asignaciones as datos_asignaciones
from apps.solicitudes.vigencia import limite_dia_operativo
from apps.usuarios.models import Usuario
from apps.usuarios.servicios import actualizar_usuario_administrado


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasContingenciasCorporativas(TestCase):
    setUpTestData = classmethod(datos_asignaciones.PruebasAsignacionesSolicitud.setUpTestData.__func__)
    _registrar_gps = datos_asignaciones.PruebasAsignacionesSolicitud._registrar_gps

    def setUp(self):
        datos_asignaciones.PruebasAsignacionesSolicitud.setUp(self)
        self.ahora = timezone.now()
        JornadaRepartidor.objects.update(iniciada_en=self.ahora - timedelta(minutes=15))
        Solicitud.objects.filter(pk=self.solicitud.pk).update(creado_en=self.ahora - timedelta(minutes=5))
        self.solicitud.refresh_from_db()
        self.anterior, self.nuevo = self.repartidores

    def _asignar(self, estado=EstadoSolicitud.ASIGNADA, especial=False):
        if especial:
            self.solicitud.modalidad = "ESPECIAL"
            self.solicitud.destino = None
            self.solicitud.destino_especial = "Encargo de prueba"
            self.solicitud.save()
        asignar_solicitud_manualmente(self.administrador, self.solicitud.pk, {"repartidor_id": self.anterior.pk})
        self.solicitud.refresh_from_db()
        asignacion = self.solicitud.asignaciones.get(estado="ACTIVA")
        asignacion.asignada_en = self.ahora - timedelta(minutes=4)
        asignacion.aceptada_en = self.ahora - timedelta(minutes=3)
        asignacion.save()
        self.solicitud.estado = estado
        if estado in ("PICKED_UP", "IN_TRANSIT", "AT_DESTINATION"):
            self.solicitud.recolectada_en = self.ahora - timedelta(minutes=2)
            if especial:
                iniciar_movimiento_especial(self.solicitud, self.anterior, ahora=self.solicitud.recolectada_en,
                    latitud=self.origen.latitud, longitud=self.origen.longitud)
        self.solicitud.save()
        return asignacion

    def _suspender(self):
        with self.captureOnCommitCallbacks(execute=True):
            actualizar_usuario_administrado(self.administrador, self.anterior.usuario, {"estado": "SUSPENDIDO"})
        self.solicitud.refresh_from_db()

    def _vencer(self, instante=None):
        inicio = instante or (self.ahora - timedelta(days=1))
        Solicitud.objects.filter(pk=self.solicitud.pk).update(creado_en=inicio)
        self.solicitud.refresh_from_db()
        return limite_dia_operativo(inicio, self.empresa)

    def test_suspension_reasigna_servicio_sin_recoger_y_notifica(self):
        anterior = self._asignar(EstadoSolicitud.EN_RECOLECCION)
        self._suspender()
        self.assertEqual(self.solicitud.repartidor_asignado_id, self.nuevo.pk)
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.HACIA_RECOLECCION)
        self.assertFalse(self.solicitud.reasignacion_pendiente)
        anterior.refresh_from_db()
        self.assertEqual(anterior.estado, "REASIGNADA")
        self.assertTrue(NotificacionUsuario.objects.filter(usuario=self.nuevo.usuario, tipo="SOLICITUD_REASIGNADA").exists())
        self.anterior.refresh_from_db()
        self.assertEqual((self.anterior.capacidad, self.anterior.estado_operativo), ("EMPTY", "OUT_OF_SERVICE"))

    def test_suspension_con_paquete_conserva_fase_y_solo_parada_de_entrega(self):
        self._asignar(EstadoSolicitud.EN_TRANSITO)
        recogida = self.solicitud.recolectada_en
        self._suspender()
        self.assertEqual(self.solicitud.repartidor_asignado_id, self.nuevo.pk)
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.EN_TRANSITO)
        self.assertEqual(self.solicitud.recolectada_en, recogida)
        self.assertEqual([p["tipo"] for p in obtener_paradas_operativas(self.nuevo)], ["ENTREGA"])
        self.assertEqual(obtener_paradas_operativas(self.anterior), [])
        self.assertIsNotNone(self.solicitud.asignaciones.get(estado="ACTIVA").aceptada_en)
        evento = self.solicitud.eventos.filter(tipo="REASIGNADA").latest("creado_en")
        self.assertTrue(evento.metadatos["traspaso_fisico_fuera_app"])
        self.assertEqual(evento.metadatos["repartidor_anterior_id"], str(self.anterior.pk))

    def test_sin_candidato_queda_pendiente_y_se_recupera_sin_perder_fase(self):
        self._asignar(EstadoSolicitud.RECOLECTADA)
        Repartidor.objects.filter(pk=self.nuevo.pk).update(estado_operativo="PAUSED")
        self._suspender()
        self.assertIsNone(self.solicitud.repartidor_asignado_id)
        self.assertTrue(self.solicitud.reasignacion_pendiente)
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.RECOLECTADA)
        self.assertFalse(self.solicitud.asignaciones.filter(estado="ACTIVA").exists())
        self.assertTrue(NotificacionUsuario.objects.filter(usuario=self.administrador, tipo="REASIGNACION_PENDIENTE").exists())
        Repartidor.objects.filter(pk=self.nuevo.pk).update(estado_operativo="AVAILABLE")
        self.assertEqual(reintentar_solicitudes_pendientes(self.empresa.pk), 1)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.RECOLECTADA)
        self.assertEqual(self.solicitud.repartidor_asignado_id, self.nuevo.pk)
        self.assertEqual(reintentar_solicitudes_pendientes(self.empresa.pk), 0)

    def test_especial_guarda_tramos_y_no_mezcla_motoristas(self):
        self._asignar(EstadoSolicitud.RECOLECTADA, especial=True)
        self._suspender()
        tramos = list(self.solicitud.movimientos_especiales.order_by("iniciada_en"))
        self.assertEqual(len(tramos), 2)
        self.assertEqual((tramos[0].repartidor_id, tramos[0].estado, tramos[0].motivo_cierre), (self.anterior.pk, "FINALIZADO", "SUSPENSION"))
        self.assertIsNone(tramos[0].latitud_fin)
        self.assertEqual((tramos[1].repartidor_id, tramos[1].estado), (self.nuevo.pk, "ACTIVO"))
        self.assertNotEqual(tramos[0].jornada_id, tramos[1].jornada_id)
        self.assertEqual(self.solicitud.movimiento_especial.pk, tramos[1].pk)
        detalle = SerializadorSolicitudDetalle(self.solicitud).data
        self.assertEqual(len(detalle["movimientos_especiales"]), 2)
        self.assertIsNone(detalle["kilometros_envio_especial"])

    def test_especial_solo_acepta_reemplazo_libre_y_sin_gps_no_lo_inicia(self):
        self._asignar(EstadoSolicitud.RECOLECTADA, especial=True)
        RegistroUbicacion.objects.filter(repartidor=self.nuevo).delete()
        self._suspender()
        self.assertTrue(self.solicitud.reasignacion_pendiente)
        self.assertEqual(self.solicitud.movimientos_especiales.count(), 1)
        self._registrar_gps(self.nuevo, "14.072300", "-87.192100")
        reintentar_solicitudes_pendientes(self.empresa.pk)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.repartidor_asignado_id, self.nuevo.pk)

    def test_resumen_atribuye_recoleccion_al_original_y_entrega_al_reemplazo(self):
        self._asignar(EstadoSolicitud.RECOLECTADA)
        self._suspender()
        # La entrega física y su foto se validan en el flujo normal; aquí se
        # aísla exclusivamente la atribución histórica del resumen.
        fin = timezone.now() + timedelta(seconds=1)
        self.solicitud.estado = EstadoSolicitud.ENTREGADA
        self.solicitud.entregada_en = fin
        self.solicitud.save()
        vieja = JornadaRepartidor.objects.get(repartidor=self.anterior)
        nueva = JornadaRepartidor.objects.get(repartidor=self.nuevo)
        a = _calcular_resumen(vieja, fin)
        b = _calcular_resumen(nueva, fin)
        self.assertEqual((a["recolecciones_completadas"], a["entregas_completadas"]), (1, 0))
        self.assertEqual((b["recolecciones_completadas"], b["entregas_completadas"]), (0, 1))

    def test_proceso_repetido_no_duplica_reasignaciones(self):
        self._asignar()
        self._suspender()
        cantidad = self.solicitud.asignaciones.count()
        avisos = NotificacionUsuario.objects.count()
        self.assertEqual(procesar_suspension(self.anterior.usuario_id, self.administrador), 0)
        self.assertEqual((self.solicitud.asignaciones.count(), NotificacionUsuario.objects.count()), (cantidad, avisos))

    def test_cierre_diario_pendiente_no_recogida(self):
        corte = self._vencer()
        self.assertTrue(cerrar_solicitud_vencida(self.solicitud.pk, corte))
        self.solicitud.refresh_from_db()
        self.assertEqual((self.solicitud.estado, self.solicitud.motivo_cierre, self.solicitud.cerrada_en), ("PICKUP_FAILED", "FIN_DIA", corte))
        self.assertFalse(cerrar_solicitud_vencida(self.solicitud.pk, corte + timedelta(days=1)))
        self.assertEqual(self.solicitud.eventos.filter(tipo="CIERRE_AUTOMATICO").count(), 1)

    def test_cierre_diario_con_paquete_no_entregado_cierra_asignacion_y_ruta(self):
        self._asignar(EstadoSolicitud.EN_TRANSITO)
        corte = self._vencer()
        JornadaRepartidor.objects.filter(repartidor=self.anterior).update(iniciada_en=corte - timedelta(hours=6), fecha_operativa=corte.date(), cierre_programado_en=corte)
        resultado = procesar_cierre_diario(corte + timedelta(hours=3))
        self.assertEqual(resultado["solicitudes_cerradas"], 1)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, "DELIVERY_FAILED")
        self.assertEqual(self.solicitud.cerrada_en, corte)
        self.assertFalse(self.solicitud.asignaciones.filter(estado="ACTIVA").exists())
        jornada = JornadaRepartidor.objects.get(repartidor=self.anterior)
        self.assertEqual((jornada.estado, jornada.finalizada_en), ("FINALIZADA", corte))
        self.assertEqual(jornada.calidad_kilometraje["estado"], "SIN_VERIFICAR")
        self.assertFalse(RutaRepartidor.objects.filter(repartidor=self.anterior, estado="ACTIVA").exists())
        self.assertEqual(procesar_cierre_diario(corte + timedelta(hours=4))["solicitudes_cerradas"], 0)

    def test_cierre_diario_respeta_zona_horaria_y_limite_exacto(self):
        corte = self._vencer()
        self.assertEqual(corte.hour, 22)
        self.assertEqual(corte.utcoffset(), timedelta(hours=-6))
        self.assertFalse(cerrar_solicitud_vencida(self.solicitud.pk, corte - timedelta(microseconds=1)))
        self.assertTrue(cerrar_solicitud_vencida(self.solicitud.pk, corte))

    def test_dia_vigente_y_terminales_historicos_no_se_modifican(self):
        self.assertFalse(cerrar_solicitud_vencida(self.solicitud.pk, self.ahora))
        self._vencer()
        self.solicitud.estado = EstadoSolicitud.ENTREGADA
        self.solicitud.save()
        self.assertFalse(cerrar_solicitud_vencida(self.solicitud.pk, self.ahora))
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.ENTREGADA)
        self.assertEqual(self.solicitud.motivo_cierre, "")

    def test_vencida_no_puede_asignarse_ni_operarse_antes_de_ejecutar_tarea(self):
        self._asignar()
        self._vencer()
        with self.assertRaises(ValidationError):
            cambiar_estado_solicitud(self.anterior.usuario, self.solicitud.pk, {"estado_destino": EstadoSolicitud.HACIA_RECOLECCION})
        with self.assertRaises(ValidationError):
            asignar_solicitud_manualmente(self.administrador, self.solicitud.pk, {"repartidor_id": self.nuevo.pk})

    def test_cierre_diario_especial_sin_gps_final_no_inventa_coordenadas(self):
        self._asignar(EstadoSolicitud.RECOLECTADA, especial=True)
        corte = limite_dia_operativo(self.solicitud.creado_en, self.empresa)
        self.assertTrue(cerrar_solicitud_vencida(self.solicitud.pk, corte))
        movimiento = self.solicitud.movimientos_especiales.get()
        self.assertEqual((movimiento.estado, movimiento.finalizada_en, movimiento.motivo_cierre), ("FINALIZADO", corte, "FIN_DIA"))
        self.assertIsNone(movimiento.latitud_fin)
        self.assertFalse(movimiento.calidad_kilometraje["sincronizacion_verificada"])

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_cierra_vencidas_sin_retirar_por_suspension_corporativa(self):
        self._vencer()
        self.assertTrue(cerrar_solicitud_vencida(self.solicitud.pk, self.ahora))
        self.assertEqual(procesar_cierre_diario(self.ahora), {"solicitudes_cerradas": 0, "servicios_retirados": 0, "jornadas_cerradas": 0})
        self.assertEqual(procesar_suspension(self.anterior.usuario_id), 0)
        with self.assertRaises(CommandError):
            call_command("cerrar_operaciones_vencidas", confirmar_corporativo=True, stdout=StringIO())

    def test_comando_exige_confirmacion(self):
        with self.assertRaises(CommandError):
            call_command("cerrar_operaciones_vencidas", stdout=StringIO())

    def test_comando_sin_consola_registra_resultado_y_no_falla_por_stdout(self):
        resultado = {"solicitudes_cerradas": 0, "servicios_retirados": 0, "jornadas_cerradas": 0}
        with patch("apps.solicitudes.management.commands.cerrar_operaciones_vencidas.procesar_cierre_diario", return_value=resultado) as procesar:
            with patch("apps.solicitudes.management.commands.cerrar_operaciones_vencidas.logging.getLogger") as obtener_logger:
                with patch("sys.stdout", None), patch("sys.stderr", None):
                    call_command("cerrar_operaciones_vencidas", confirmar_corporativo=True, skip_checks=True)
        procesar.assert_called_once_with()
        obtener_logger.return_value.info.assert_called_once()

    def test_comando_sin_consola_conserva_error_si_hubo_fallos_operativos(self):
        with patch("apps.solicitudes.management.commands.cerrar_operaciones_vencidas.procesar_cierre_diario", return_value={"errores": 1}):
            with patch("apps.solicitudes.management.commands.cerrar_operaciones_vencidas.logging.getLogger"):
                with patch("sys.stdout", None), patch("sys.stderr", None):
                    with self.assertRaises(CommandError):
                        call_command("cerrar_operaciones_vencidas", confirmar_corporativo=True, skip_checks=True)

    def test_reemplazo_lleno_no_recibe_una_sexta_solicitud(self):
        self._asignar()
        for indice in range(5):
            Solicitud.objects.create(cantidad_tubos=1, numero=f"LLENO-{indice}", empresa=self.empresa,
                solicitada_por=self.administrador, repartidor_asignado=self.nuevo,
                origen=self.origen, destino=self.destino, prioridad="NORMAL", estado="ASSIGNED")
        self._suspender()
        self.assertTrue(self.solicitud.reasignacion_pendiente)
        self.assertIsNone(self.solicitud.repartidor_asignado_id)
        self.assertEqual(Solicitud.objects.filter(repartidor_asignado=self.nuevo, estado="ASSIGNED").count(), 5)

    def test_reemplazo_con_prioritario_no_recibe_contingencia(self):
        self._asignar()
        Solicitud.objects.create(cantidad_tubos=1, numero="PRIORITARIO-ACTIVO", empresa=self.empresa,
            solicitada_por=self.administrador, repartidor_asignado=self.nuevo,
            origen=self.origen, destino=self.destino, prioridad="PRIORITY", estado="IN_TRANSIT")
        self._suspender()
        self.assertTrue(self.solicitud.reasignacion_pendiente)

    def test_no_toma_reemplazo_de_otra_empresa(self):
        from apps.organizaciones.models import Empresa
        from apps.flota.models import Vehiculo
        from apps.usuarios.models import RolUsuario

        otra = Empresa.objects.create(nombre="Otra empresa", pais=self.pais)
        Usuario.objetos.filter(pk=self.nuevo.usuario_id).update(empresa=otra)
        RolUsuario.objetos.filter(usuario_id=self.nuevo.usuario_id).update(empresa=otra)
        Vehiculo.objects.filter(pk=self.nuevo.vehiculo_id).update(empresa=otra)
        Repartidor.objects.filter(pk=self.nuevo.pk).update(empresa=otra)
        self._asignar()
        self._suspender()
        self.assertTrue(self.solicitud.reasignacion_pendiente)
        self.assertIsNone(self.solicitud.repartidor_asignado_id)

    def test_continuar_entrega_manualmente_exige_jornada_del_reemplazo(self):
        self._asignar(EstadoSolicitud.RECOLECTADA)
        Repartidor.objects.filter(pk=self.nuevo.pk).update(estado_operativo="PAUSED")
        self._suspender()
        RegistroUbicacion.objects.filter(repartidor=self.nuevo).delete()
        JornadaRepartidor.objects.filter(repartidor=self.nuevo).delete()
        Repartidor.objects.filter(pk=self.nuevo.pk).update(estado_operativo="AVAILABLE")
        with self.assertRaises(ValidationError) as rechazo:
            asignar_solicitud_manualmente(self.administrador, self.solicitud.pk, {"repartidor_id": self.nuevo.pk})
        self.assertIn("repartidor_id", rechazo.exception.detail)

    def test_rollback_de_suspension_no_retira_servicios(self):
        self._asignar()
        with self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                actualizar_usuario_administrado(self.administrador, self.anterior.usuario, {"estado": "SUSPENDIDO"})
                transaction.set_rollback(True)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.repartidor_asignado_id, self.anterior.pk)
        self.assertFalse(self.solicitud.reasignacion_pendiente)

    def test_tarea_recupera_una_suspension_cuyo_callback_fallo(self):
        self._asignar()
        with patch("apps.solicitudes.contingencias.procesar_suspension", side_effect=RuntimeError("Fallo simulado")):
            with self.assertLogs("vitago.api", level="ERROR"):
                self._suspender()
        self.assertEqual(self.solicitud.repartidor_asignado_id, self.anterior.pk)
        with self.captureOnCommitCallbacks(execute=True):
            resultado = procesar_cierre_diario()
        self.assertEqual(resultado["servicios_retirados"], 1)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.repartidor_asignado_id, self.nuevo.pk)

    def test_anterior_puede_sincronizar_su_tramo_sin_controlar_el_nuevo(self):
        self._asignar(EstadoSolicitud.RECOLECTADA, especial=True)
        self._suspender()
        anterior = self.solicitud.movimientos_especiales.get(repartidor=self.anterior)
        Usuario.objetos.filter(pk=self.anterior.usuario_id).update(estado="ACTIVO")
        self.anterior.usuario.refresh_from_db()
        resultado = confirmar_sincronizacion_movimiento(self.anterior.usuario, self.solicitud.pk, {
            "sesiones_gps": [], "movimiento_id": anterior.pk,
        })
        self.assertEqual(resultado.pk, anterior.pk)
        with self.assertRaises(Http404):
            confirmar_sincronizacion_movimiento(self.anterior.usuario, self.solicitud.pk, {
                "sesiones_gps": [], "movimiento_id": self.solicitud.movimiento_especial.pk,
            })

    def test_varios_traspasos_conservan_todos_los_tramos(self):
        self._asignar(EstadoSolicitud.RECOLECTADA, especial=True)
        self._suspender()
        Usuario.objetos.filter(pk=self.anterior.usuario_id).update(estado="ACTIVO")
        Repartidor.objects.filter(pk=self.anterior.pk).update(estado_operativo="AVAILABLE")
        with self.captureOnCommitCallbacks(execute=True):
            actualizar_usuario_administrado(self.administrador, self.nuevo.usuario, {"estado": "SUSPENDIDO"})
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.repartidor_asignado_id, self.anterior.pk)
        self.assertEqual(self.solicitud.movimientos_especiales.count(), 3)
        self.anterior.usuario.refresh_from_db()
        # Hay un tramo anterior finalizado y otro activo: se confirma el cerrado.
        cerrado = self.solicitud.movimientos_especiales.filter(repartidor=self.anterior, estado="FINALIZADO").get()
        self.assertEqual(confirmar_sincronizacion_movimiento(self.anterior.usuario, self.solicitud.pk, {
            "movimiento_id": cerrado.pk, "sesiones_gps": [],
        }).pk, cerrado.pk)

    def test_gps_no_cruza_medianoche_y_admite_cola_anterior_despues_del_cierre(self):
        from apps.seguimiento.servicios import registrar_ubicaciones

        corte = limite_dia_operativo(self.ahora - timedelta(days=1), self.empresa)
        jornada = JornadaRepartidor.objects.get(repartidor=self.anterior)
        jornada.iniciada_en = corte - timedelta(hours=6)
        jornada.fecha_operativa = corte.date()
        jornada.cierre_programado_en = corte
        jornada.save()
        punto = {"id_cliente": uuid4(), "latitud": self.origen.latitud, "longitud": self.origen.longitud,
                 "precision_metros": Decimal("8"), "registrada_en": corte + timedelta(seconds=1)}
        with self.assertRaises(ValidationError):
            registrar_ubicaciones(self.anterior.usuario, {"jornada_id": jornada.pk, "registros": [punto]})
        procesar_cierre_diario(self.ahora)
        jornada.refresh_from_db()
        self.assertEqual(jornada.finalizada_en, corte)
        punto["registrada_en"] = corte - timedelta(seconds=1)
        self.assertEqual(registrar_ubicaciones(self.anterior.usuario, {"jornada_id": jornada.pk, "registros": [punto]})["creados"], 1)

    def test_reintento_cierra_vencida_y_continua_con_la_vigente(self):
        self._vencer()
        vigente = Solicitud.objects.create(cantidad_tubos=1, numero="VIGENTE-REINTENTO", empresa=self.empresa,
            solicitada_por=self.administrador, origen=self.origen, destino=self.destino, prioridad="NORMAL")
        self.assertEqual(reintentar_solicitudes_pendientes(self.empresa.pk), 1)
        self.solicitud.refresh_from_db()
        vigente.refresh_from_db()
        self.assertEqual(self.solicitud.estado, "PICKUP_FAILED")
        self.assertEqual(vigente.estado, "ASSIGNED")

    def test_cierre_normal_de_especial_no_permite_gps_final_nulo(self):
        self._asignar(EstadoSolicitud.RECOLECTADA, especial=True)
        movimiento = self.solicitud.movimiento_especial
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MovimientoEnvioEspecial.objects.filter(pk=movimiento.pk).update(
                    estado="FINALIZADO", finalizada_en=timezone.now(), motivo_cierre="", latitud_fin=None, longitud_fin=None,
                )

    def test_cancelar_una_contingencia_pendiente_no_resucita_el_servicio(self):
        self._asignar()
        Repartidor.objects.filter(pk=self.nuevo.pk).update(estado_operativo="PAUSED")
        self._suspender()
        self.assertTrue(self.solicitud.reasignacion_pendiente)
        cambiar_estado_solicitud(self.administrador, self.solicitud.pk, {"estado_destino": "CANCELLED", "motivo": "Ya no se requiere"})
        Repartidor.objects.filter(pk=self.nuevo.pk).update(estado_operativo="AVAILABLE")
        self.assertEqual(reintentar_solicitudes_pendientes(self.empresa.pk), 0)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, "CANCELLED")
        self.assertFalse(self.solicitud.reasignacion_pendiente)
        self.assertIsNotNone(self.solicitud.cerrada_en)

    def test_un_cierre_fallido_no_impide_cerrar_los_demas(self):
        self._vencer()
        otra = Solicitud.objects.create(cantidad_tubos=1, numero="SEGUNDA-VENCIDA", empresa=self.empresa,
            solicitada_por=self.administrador, origen=self.origen, destino=self.destino, prioridad="NORMAL")
        Solicitud.objects.filter(pk=otra.pk).update(creado_en=self.solicitud.creado_en)
        original = cerrar_solicitud_vencida
        def ejecutar(pk, ahora):
            if pk == self.solicitud.pk:
                raise RuntimeError("Fallo simulado")
            return original(pk, ahora)
        with patch("apps.solicitudes.contingencias.cerrar_solicitud_vencida", side_effect=ejecutar):
            with self.assertLogs("vitago.api", level="ERROR"):
                resultado = procesar_cierre_diario(self.ahora)
        self.assertEqual((resultado["solicitudes_cerradas"], resultado["errores"]), (1, 1))
        otra.refresh_from_db()
        self.assertEqual(otra.estado, "PICKUP_FAILED")
