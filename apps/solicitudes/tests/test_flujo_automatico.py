"""Servicio vigente automático, evidencia atómica y recuperación sin aceptación."""

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.evidencias.models import EvidenciaSolicitud
from apps.evidencias.servicios import registrar_evidencia
from apps.evidencias.tests import test_operacion as datos_operacion
from apps.flota.models import Vehiculo
from apps.jornadas.models import JornadaRepartidor
from apps.rutas.models import VersionRuta
from apps.rutas.servicios import sincronizar_ruta
from apps.seguimiento.models import RegistroUbicacion
from apps.solicitudes.flujo_automatico import activar_siguiente_servicio, programar_avance_automatico
from apps.solicitudes.models import AsignacionSolicitud, EventoSolicitud, MovimientoEnvioEspecial, Solicitud
from apps.solicitudes.opciones import EstadoSolicitud, TipoEventoSolicitud
from apps.solicitudes.servicios import cambiar_estado_solicitud
from apps.usuarios.models import Rol, RolUsuario


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasFlujoAutomatico(TestCase):
    setUpTestData = classmethod(datos_operacion.PruebasOperacionConEvidencias.setUpTestData.__func__)
    _archivo_png = datos_operacion.PruebasOperacionConEvidencias._archivo_png
    _registrar = datos_operacion.PruebasOperacionConEvidencias._registrar
    _transicion = datos_operacion.PruebasOperacionConEvidencias._transicion

    def setUp(self):
        datos_operacion.PruebasOperacionConEvidencias.setUp(self)
        self.ahora = timezone.now()
        JornadaRepartidor.objects.filter(pk=self.jornada.pk).update(iniciada_en=self.ahora - timedelta(minutes=10))
        self.gps = self._gps()
        with transaction.atomic():
            sincronizar_ruta(self.repartidor, VersionRuta.Motivo.ASIGNACION)
        from rest_framework.test import APIClient
        self.cliente = APIClient()
        self.cliente.force_authenticate(self.usuario_repartidor)
        self.enterContext(patch("apps.rutas.proveedor_google.urlopen", side_effect=AssertionError("Sin Google real.")))

    def _gps(self, **cambios):
        return RegistroUbicacion.objects.create(**{
            "id_cliente": uuid4(), "repartidor": self.repartidor, "jornada": self.jornada,
            "latitud": self.origen.latitud, "longitud": self.origen.longitud,
            "precision_metros": "5", "registrada_en": timezone.now(), **cambios,
        })

    def _estado(self, estado):
        Solicitud.objects.filter(pk=self.solicitud.pk).update(estado=estado)
        self.solicitud.refresh_from_db()

    def _segunda(self, estado=EstadoSolicitud.ASIGNADA):
        solicitud = Solicitud.objects.create(
            cantidad_tubos=1,
            numero=f"SOL-COLA-{uuid4().hex[:8]}", empresa=self.empresa, solicitada_por=self.administrador,
            repartidor_asignado=self.repartidor, prioridad="NORMAL", tipo_servicio=self.tipo_servicio,
            origen=self.origen, destino=self.destino, estado=estado, asignada_en=timezone.now(),
        )
        AsignacionSolicitud.objects.create(solicitud=solicitud, repartidor=self.repartidor, asignada_por=self.administrador)
        sincronizar_ruta(self.repartidor, VersionRuta.Motivo.ASIGNACION)
        return solicitud

    def _activar(self):
        return activar_siguiente_servicio(self.repartidor.pk)

    def _leer(self):
        respuesta = self.cliente.get(reverse("rutas:mi-ruta"))
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        return respuesta.data

    def _subir_foto(self, tipo="FOTO_RECOLECCION", archivo=None):
        return self.cliente.post(reverse("solicitudes:evidencias:lista-registro", args=[self.solicitud.pk]), {
            "tipo": tipo, "archivo": archivo or self._archivo_png(),
            **({"temperatura_contenedor_c": "4.50"} if tipo == "FOTO_RECOLECCION" else {}),
            "latitud": str(self.origen.latitud), "longitud": str(self.origen.longitud),
        }, format="multipart")

    def test_activa_sin_aceptar_y_audita_hora_servidor(self):
        resultado = self._activar()
        self.assertEqual(resultado.estado, EstadoSolicitud.HACIA_RECOLECCION)
        evento = EventoSolicitud.objects.get(solicitud=self.solicitud, tipo=TipoEventoSolicitud.HACIA_RECOLECCION)
        self.assertEqual(evento.metadatos["automatismo"]["fuente"], "ACTIVACION_SERVICIO")
        asignacion = AsignacionSolicitud.objects.get(solicitud=self.solicitud)
        self.assertIsNotNone(asignacion.aceptada_en)
        self.assertGreaterEqual(asignacion.aceptada_en, self.ahora)

    def test_activa_unicamente_primero_y_no_toda_cola(self):
        segunda = self._segunda()
        self._activar()
        segunda.refresh_from_db()
        self.assertEqual(segunda.estado, EstadoSolicitud.ASIGNADA)
        self.assertEqual(Solicitud.objects.filter(estado=EstadoSolicitud.HACIA_RECOLECCION).count(), 1)

    def test_repetir_activacion_no_duplica_eventos_ni_versiones(self):
        self._activar()
        versiones = VersionRuta.objects.count()
        for _ in range(3):
            self.assertIsNone(self._activar())
        self.assertEqual(EventoSolicitud.objects.filter(tipo=TipoEventoSolicitud.HACIA_RECOLECCION).count(), 1)
        self.assertEqual(VersionRuta.objects.count(), versiones)

    def test_espera_gps_valido_sin_iniciar_etapa(self):
        for cambios in ({"precision_metros": None}, {"precision_metros": "500"},
                        {"registrada_en": self.ahora - timedelta(hours=1)},
                        {"registrada_en": self.ahora + timedelta(minutes=5)}):
            with self.subTest(cambios=cambios):
                RegistroUbicacion.objects.filter(pk=self.gps.pk).update(registrada_en=self.ahora, precision_metros="5")
                RegistroUbicacion.objects.filter(pk=self.gps.pk).update(**cambios)
                self.assertIsNone(self._activar())
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.ASIGNADA)
        self.assertFalse(EventoSolicitud.objects.exists())

    def test_no_inicia_motorista_pausado_desconectado_o_fuera_servicio(self):
        for estado in ("PAUSED", "OFFLINE", "OUT_OF_SERVICE"):
            with self.subTest(estado=estado):
                type(self.repartidor).objects.filter(pk=self.repartidor.pk).update(estado_operativo=estado)
                self.assertIsNone(self._activar())
        self.assertFalse(EventoSolicitud.objects.exists())

    def test_no_inicia_sin_jornada_activa(self):
        JornadaRepartidor.objects.filter(pk=self.jornada.pk).update(estado="FINALIZADA", finalizada_en=self.ahora)
        self.assertIsNone(self._activar())

    def test_no_inicia_jornada_del_dia_anterior(self):
        JornadaRepartidor.objects.filter(pk=self.jornada.pk).update(iniciada_en=self.ahora - timedelta(days=1), cierre_programado_en=self.ahora - timedelta(hours=1))
        self.assertIsNone(self._activar())

    def test_no_inicia_si_usuario_fue_suspendido(self):
        type(self.usuario_repartidor).objetos.filter(pk=self.usuario_repartidor.pk).update(estado="SUSPENDIDO")
        self.assertIsNone(self._activar())

    def test_no_inicia_si_rol_operativo_fue_retirado(self):
        RolUsuario.objetos.filter(usuario=self.usuario_repartidor).update(activo=False, revocado_en=self.ahora)
        self.assertIsNone(self._activar())

    def test_no_inicia_sin_motocicleta_activa(self):
        Vehiculo.objects.filter(pk=self.repartidor.vehiculo_id).update(estado="INACTIVO")
        self.assertIsNone(self._activar())

    def test_foto_recoleccion_avanza_hasta_traslado_en_misma_transaccion(self):
        self._estado(EstadoSolicitud.EN_RECOLECCION)
        evidencia = self._registrar("FOTO_RECOLECCION")
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.EN_TRANSITO)
        self.assertIsNotNone(self.solicitud.recolectada_en)
        for tipo in (TipoEventoSolicitud.RECOLECTADA, TipoEventoSolicitud.EN_TRANSITO):
            evento = EventoSolicitud.objects.get(solicitud=self.solicitud, tipo=tipo)
            self.assertEqual(evento.metadatos["automatismo"], {"fuente": "EVIDENCIA", "evidencia_id": str(evidencia.pk)})
        self.assertEqual(self._leer()["flujo_actual"]["tipo_parada"], "ENTREGA")

    def test_foto_entrega_finaliza_y_libera_cupo(self):
        self._estado(EstadoSolicitud.EN_DESTINO)
        self._registrar("FOTO_ENTREGA")
        self.solicitud.refresh_from_db()
        self.repartidor.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.ENTREGADA)
        self.assertEqual(self.repartidor.capacidad, "EMPTY")
        self.assertEqual(AsignacionSolicitud.objects.get(solicitud=self.solicitud).estado, "FINALIZADA")
        self.assertEqual(self._leer()["flujo_actual"]["pantalla"], "SIN_SERVICIOS")

    def test_entrega_activa_siguiente_sin_pedir_otra_confirmacion(self):
        self._estado(EstadoSolicitud.EN_DESTINO)
        segunda = self._segunda()
        with self.captureOnCommitCallbacks(execute=True):
            self._registrar("FOTO_ENTREGA")
        segunda.refresh_from_db()
        self.assertEqual(segunda.estado, EstadoSolicitud.HACIA_RECOLECCION)
        self.assertEqual(self._leer()["flujo_actual"]["solicitud_id"], str(segunda.pk))

    def test_foto_incidencia_no_completa_etapa(self):
        self._estado(EstadoSolicitud.EN_RECOLECCION)
        self._registrar("FOTO_INCIDENCIA")
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.EN_RECOLECCION)
        self.assertFalse(EventoSolicitud.objects.filter(tipo=TipoEventoSolicitud.RECOLECTADA).exists())

    def test_foto_corrupta_no_completa_ni_guarda_archivo(self):
        self._estado(EstadoSolicitud.EN_RECOLECCION)
        respuesta = self._subir_foto(archivo=SimpleUploadedFile("rota.png", b"incorrecto", content_type="image/png"))
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("archivo", respuesta.data)
        self.assertFalse(EvidenciaSolicitud.objects.exists())
        self.assertFalse(EventoSolicitud.objects.exists())

    def test_fallo_segunda_transicion_revierte_foto_primera_transicion_y_eventos(self):
        self._estado(EstadoSolicitud.EN_RECOLECCION)
        def cambiar(usuario, identificador, datos, **opciones):
            if datos["estado_destino"] == EstadoSolicitud.EN_TRANSITO:
                raise ValidationError({"estado_destino": "Fallo simulado"})
            return cambiar_estado_solicitud(usuario, identificador, datos, **opciones)
        with patch("apps.solicitudes.servicios.cambiar_estado_solicitud", side_effect=cambiar), \
                patch("apps.evidencias.servicios.default_storage.delete") as eliminar:
            with self.assertRaises(ValidationError):
                self._registrar("FOTO_RECOLECCION")
            eliminar.assert_called_once()
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.EN_RECOLECCION)
        self.assertFalse(EvidenciaSolicitud.objects.exists())
        self.assertFalse(EventoSolicitud.objects.exists())

    def test_permiso_de_transicion_no_se_omite_por_subir_foto(self):
        self._estado(EstadoSolicitud.EN_RECOLECCION)
        with patch("apps.solicitudes.servicios.usuario_tiene_permiso", return_value=False):
            respuesta = self._subir_foto()
        self.assertEqual(respuesta.status_code, 403)
        self.assertFalse(EvidenciaSolicitud.objects.exists())
        self.assertFalse(EventoSolicitud.objects.exists())

    def test_no_puede_iniciar_segundo_servicio_manualmente(self):
        segunda = self._segunda()
        with self.assertRaises(ValidationError) as error:
            cambiar_estado_solicitud(self.usuario_repartidor, segunda.pk, {"estado_destino": "GOING_TO_PICKUP"})
        self.assertIn("estado_destino", error.exception.detail)

    def test_no_puede_subir_foto_de_otra_etapa_fuera_del_servicio_vigente(self):
        self._estado(EstadoSolicitud.EN_TRANSITO)
        segunda = self._segunda(EstadoSolicitud.EN_RECOLECCION)
        with self.assertRaises(ValidationError):
            registrar_evidencia(self.usuario_repartidor, segunda.pk, {
                "tipo": "FOTO_RECOLECCION", "archivo": self._archivo_png(),
                "latitud": self.origen.latitud, "longitud": self.origen.longitud,
            })
        self.assertFalse(EvidenciaSolicitud.objects.exists())

    def test_especial_foto_recoge_abre_movimiento_y_destino_sigue_manual(self):
        Solicitud.objects.filter(pk=self.solicitud.pk).update(modalidad="ESPECIAL", destino=None, destino_especial="Encargo de prueba")
        self._estado(EstadoSolicitud.EN_RECOLECCION)
        self._registrar("FOTO_RECOLECCION")
        self.assertTrue(MovimientoEnvioEspecial.objects.filter(solicitud=self.solicitud, estado="ACTIVO").exists())
        flujo = self._leer()["flujo_actual"]
        self.assertEqual(flujo["pantalla"], "FINALIZAR_ESPECIAL")
        self.assertTrue(flujo["requiere_finalizacion_especial"])
        self.assertIsNone(flujo["evidencia_requerida"])
        cambiar_estado_solicitud(self.usuario_repartidor, self.solicitud.pk, {"estado_destino": EstadoSolicitud.EN_DESTINO})
        self._registrar("FOTO_ENTREGA")
        self.assertTrue(MovimientoEnvioEspecial.objects.filter(solicitud=self.solicitud, estado="FINALIZADO").exists())

    def test_especial_no_se_recoge_ni_levanta_pausa_por_foto(self):
        Solicitud.objects.filter(pk=self.solicitud.pk).update(modalidad="ESPECIAL", destino=None, destino_especial="Encargo de prueba")
        self._estado(EstadoSolicitud.EN_RECOLECCION)
        type(self.repartidor).objects.filter(pk=self.repartidor.pk).update(estado_operativo="PAUSED")
        with self.assertRaises(ValidationError):
            self._registrar("FOTO_RECOLECCION")
        self.assertFalse(MovimientoEnvioEspecial.objects.exists())
        self.assertFalse(EvidenciaSolicitud.objects.exists())

    def test_flujo_actual_no_escribe_ni_necesita_geometria(self):
        with override_settings(HABILITAR_RUTAS_GOOGLE=False, CLAVE_API_GOOGLE_MAPS=""):
            with CaptureQueriesContext(connection) as consultas:
                flujo = self._leer()["flujo_actual"]
        self.assertTrue(all(c["sql"].lstrip().upper().startswith("SELECT") for c in consultas))
        self.assertEqual(flujo["modo"], "AUTOMATICO")
        self.assertFalse(flujo["permite_elegir_etapa"])
        self.assertFalse(flujo["requiere_aceptacion"])
        self.assertEqual(flujo["tramo_id"], f"{self.solicitud.pk}:RECOLECCION")
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.ASIGNADA)

    def test_pantalla_evidencia_se_deduce_de_estado_no_de_seleccion(self):
        for estado, pantalla, foto in ((EstadoSolicitud.EN_RECOLECCION, "RECOLECCION", "FOTO_RECOLECCION"),
                                      (EstadoSolicitud.EN_DESTINO, "ENTREGA", "FOTO_ENTREGA")):
            with self.subTest(estado=estado):
                self._estado(estado)
                flujo = self._leer()["flujo_actual"]
                self.assertEqual(flujo["pantalla"], pantalla)
                self.assertEqual(flujo["evidencia_requerida"], foto)

    def test_http_foto_201_informa_estado_actual_y_no_pide_post_transicion(self):
        self._estado(EstadoSolicitud.EN_RECOLECCION)
        respuesta = self._subir_foto()
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        self.assertEqual(respuesta.data["estado_solicitud"], "IN_TRANSIT")
        self.assertEqual(self._leer()["flujo_actual"]["tipo_parada"], "ENTREGA")

    def test_reenvio_foto_no_duplica_transiciones_y_get_recupera_estado(self):
        self._estado(EstadoSolicitud.EN_RECOLECCION)
        self.assertEqual(self._subir_foto().status_code, 201)
        cantidad = EventoSolicitud.objects.count()
        respuesta = self._subir_foto()
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("tipo", respuesta.data)
        self.assertEqual(EventoSolicitud.objects.count(), cantidad)
        self.assertEqual(EvidenciaSolicitud.objects.count(), 1)
        self.assertEqual(self._leer()["flujo_actual"]["estado"], "IN_TRANSIT")

    def test_rollback_no_activa_servicio(self):
        with self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                programar_avance_automatico(self.repartidor.pk)
                transaction.set_rollback(True)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.ASIGNADA)

    def test_fallo_activador_se_registra_y_proximo_intento_recupera(self):
        with patch("apps.solicitudes.flujo_automatico.activar_siguiente_servicio", side_effect=RuntimeError("Prueba")), \
                self.assertLogs("vitago.api", level="ERROR"):
            with self.captureOnCommitCallbacks(execute=True):
                programar_avance_automatico(self.repartidor.pk)
        self.assertIsNotNone(self._activar())

    def test_flujo_completo_solo_activacion_gps_y_fotos(self):
        self._activar()
        self._transicion(EstadoSolicitud.EN_RECOLECCION)  # GPS real de la fixture, no POST manual.
        self._registrar("FOTO_RECOLECCION")
        self._transicion(EstadoSolicitud.EN_DESTINO)
        self._registrar("FOTO_ENTREGA")
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.ENTREGADA)
        self.assertEqual(EvidenciaSolicitud.objects.count(), 2)

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_activa_motorista_global_sin_aceptacion(self):
        type(self.usuario_repartidor).objetos.filter(pk=self.usuario_repartidor.pk).update(empresa=None)
        type(self.repartidor).objects.filter(pk=self.repartidor.pk).update(empresa=None)
        Vehiculo.objects.filter(pk=self.repartidor.vehiculo_id).update(empresa=None)
        RolUsuario.objetos.filter(usuario=self.usuario_repartidor).update(activo=False, revocado_en=self.ahora)
        RolUsuario.objetos.create(usuario=self.usuario_repartidor, rol=Rol.objetos.get(codigo="REPARTIDOR_RED"), tipo_alcance="GLOBAL", asignado_por=self.administrador)
        self.assertEqual(self._activar().estado, EstadoSolicitud.HACIA_RECOLECCION)


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasHTTPFlujoAutomatico(TransactionTestCase):
    serialized_rollback = True
    _archivo_png = PruebasFlujoAutomatico._archivo_png
    _gps = PruebasFlujoAutomatico._gps
    _leer = PruebasFlujoAutomatico._leer
    _subir_foto = PruebasFlujoAutomatico._subir_foto

    def setUp(self):
        datos_operacion.PruebasOperacionConEvidencias.setUpTestData.__func__(type(self))
        PruebasFlujoAutomatico.setUp(self)

    def _enviar_gps(self):
        return self.cliente.post(reverse("seguimiento:registros"), {
            "jornada_id": str(self.jornada.pk), "registros": [{
                "id_cliente": str(uuid4()), "latitud": str(self.origen.latitud),
                "longitud": str(self.origen.longitud), "precision_metros": "5",
                "registrada_en": timezone.now().isoformat(),
            }],
        }, format="json")

    def test_gps_activa_tras_commit_sin_aceptacion_y_no_finge_llegada(self):
        self.assertFalse(connection.in_atomic_block)
        respuesta = self._enviar_gps()
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        self.assertEqual(respuesta.data["llegadas_detectadas"], [])
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.HACIA_RECOLECCION)
        self._enviar_gps()
        self.assertEqual(EventoSolicitud.objects.filter(tipo=TipoEventoSolicitud.HACIA_RECOLECCION).count(), 1)

    def test_http_foto_entrega_ya_esta_confirmada_al_responder(self):
        Solicitud.objects.filter(pk=self.solicitud.pk).update(estado=EstadoSolicitud.EN_DESTINO)
        respuesta = self._subir_foto("FOTO_ENTREGA")
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        self.assertEqual(respuesta.json()["estado_solicitud"], "DELIVERED")
        self.assertEqual(self._leer()["flujo_actual"]["pantalla"], "SIN_SERVICIOS")
