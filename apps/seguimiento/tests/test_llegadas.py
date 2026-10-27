"""Llegadas por GPS propio: permanencia, orden, seguridad y contrato HTTP."""

import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.jornadas.opciones import EstadoJornada
from apps.seguimiento.models import RegistroUbicacion
from apps.seguimiento.servicios import registrar_ubicaciones
from apps.seguimiento.tests import test_seguimiento as datos_seguimiento
from apps.solicitudes.models import AsignacionSolicitud, EventoSolicitud, Solicitud
from apps.solicitudes.opciones import (
    EstadoAsignacionSolicitud,
    EstadoSolicitud,
    ModalidadSolicitud,
    TipoEventoSolicitud,
)
from apps.solicitudes.servicios import cambiar_estado_solicitud
from apps.usuarios.models import Rol, RolUsuario


@override_settings(
    MODO_APLICACION="CORPORATIVO",
    PROVEEDOR_AUTENTICACION="LOCAL",
    LLEGADAS_AUTOMATICAS_HABILITADAS=True,
    RADIO_LLEGADA_METROS=50,
    PERMANENCIA_LLEGADA_SEGUNDOS=10,
    MINIMO_PUNTOS_LLEGADA=3,
    PRECISION_LLEGADA_MAXIMA_METROS=20,
    ANTIGUEDAD_LLEGADA_MAXIMA_SEGUNDOS=30,
)
class PruebasLlegadasAutomaticas(TestCase):
    setUpTestData = classmethod(
        datos_seguimiento.PruebasSeguimiento.setUpTestData.__func__
    )

    def setUp(self):
        datos_seguimiento.PruebasSeguimiento.setUp(self)
        self.bloqueo_google = patch(
            "apps.rutas.proveedor_google.urlopen",
            side_effect=AssertionError("Una llegada GPS no debe consultar a Google."),
        )
        self.bloqueo_google.start()
        self.addCleanup(self.bloqueo_google.stop)
        Solicitud.objects.filter(pk=self.solicitud.pk).update(
            creado_en=self.ahora - timedelta(minutes=10)
        )
        self.solicitud.refresh_from_db()
        self._preparar_estado(EstadoSolicitud.HACIA_RECOLECCION)

    def _preparar_estado(self, estado, hace_segundos=60):
        self.solicitud.estado = estado
        if estado in (
            EstadoSolicitud.RECOLECTADA,
            EstadoSolicitud.EN_TRANSITO,
            EstadoSolicitud.EN_DESTINO,
        ):
            self.solicitud.recolectada_en = self.ahora - timedelta(minutes=2)
        self.solicitud.save()
        tipo = (
            TipoEventoSolicitud.EN_TRANSITO
            if estado == EstadoSolicitud.EN_TRANSITO
            else TipoEventoSolicitud.HACIA_RECOLECCION
        )
        evento = EventoSolicitud.objects.create(
            solicitud=self.solicitud,
            realizado_por=self.usuario_repartidor,
            repartidor=self.repartidor,
            tipo=tipo,
            metadatos={"estado_nuevo": estado},
        )
        EventoSolicitud.objects.filter(pk=evento.pk).update(
            creado_en=self.ahora - timedelta(seconds=hace_segundos)
        )

    def _punto(
        self, hace_segundos, *, ubicacion=None, precision=Decimal("8"),
        recibido_hace_segundos=None,
    ):
        ubicacion = ubicacion or self.origen
        punto = RegistroUbicacion.objects.create(
            id_cliente=uuid.uuid4(),
            repartidor=self.repartidor,
            jornada=self.jornada,
            latitud=ubicacion.latitud,
            longitud=ubicacion.longitud,
            precision_metros=precision,
            registrada_en=self.ahora - timedelta(seconds=hace_segundos),
            es_operativo=True,
        )
        recibido = (
            hace_segundos if recibido_hace_segundos is None
            else recibido_hace_segundos
        )
        RegistroUbicacion.objects.filter(pk=punto.pk).update(
            creado_en=self.ahora - timedelta(seconds=recibido)
        )
        punto.refresh_from_db()
        return punto

    def _permanencia(self, *, ubicacion=None, tiempos=(15, 8, 1), **opciones):
        return [
            self._punto(segundos, ubicacion=ubicacion, **opciones)
            for segundos in tiempos
        ]

    def _detectar(self, usuario=None):
        from apps.seguimiento.llegadas import detectar_llegada

        with patch("apps.seguimiento.llegadas.timezone.now", return_value=self.ahora):
            return detectar_llegada(
                usuario or self.usuario_repartidor,
                self.repartidor.pk,
                self.jornada.pk,
            )

    def _assert_sin_llegada(self):
        estado = self.solicitud.estado
        self.assertIsNone(self._detectar())
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, estado)
        self.assertFalse(EventoSolicitud.objects.filter(
            solicitud=self.solicitud,
            tipo__in=(
                TipoEventoSolicitud.LLEGADA_RECOLECCION,
                TipoEventoSolicitud.LLEGADA_DESTINO,
            ),
        ).exists())

    def _cliente(self, usuario=None):
        cliente = APIClient()
        cliente.force_authenticate(usuario or self.usuario_repartidor)
        return cliente

    def test_llegada_recoleccion_tres_capturas_y_permanencia_real(self):
        puntos = self._permanencia()

        resultado = self._detectar()

        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.EN_RECOLECCION)
        self.assertEqual(self.solicitud.llegada_recoleccion_en, self.ahora)
        self.assertIsNone(self.solicitud.recolectada_en)
        self.assertIsNone(self.solicitud.entregada_en)
        self.assertEqual(resultado["solicitud_id"], str(self.solicitud.pk))
        self.assertEqual(resultado["estado"], "AT_PICKUP")
        self.assertEqual(resultado["tipo_parada"], "RECOLECCION")
        self.assertEqual(resultado["pantalla"], "RECOLECCION")
        self.assertEqual(resultado["fuente"], "GPS")
        self.assertEqual(resultado["ruta"], f"/solicitudes/{self.solicitud.pk}")
        evento = EventoSolicitud.objects.get(pk=resultado["evento_id"])
        self.assertEqual(evento.tipo, TipoEventoSolicitud.LLEGADA_RECOLECCION)
        self.assertEqual(evento.repartidor_id, self.repartidor.pk)
        self.assertEqual(evento.realizado_por_id, self.usuario_repartidor.pk)
        prueba = evento.metadatos["llegada_gps"]
        self.assertEqual(prueba["cantidad_puntos"], 3)
        self.assertEqual(prueba["primer_registro_id"], str(puntos[0].pk))
        self.assertEqual(prueba["ultimo_registro_id"], str(puntos[-1].pk))
        self.assertGreaterEqual(prueba["permanencia_captura_segundos"], 10)
        self.assertGreaterEqual(prueba["permanencia_servidor_segundos"], 10)

    def test_llegada_destino_no_finaliza_entrega(self):
        self._preparar_estado(EstadoSolicitud.EN_TRANSITO)
        self._permanencia(ubicacion=self.destino)

        resultado = self._detectar()

        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.EN_DESTINO)
        self.assertEqual(self.solicitud.llegada_destino_en, self.ahora)
        self.assertIsNone(self.solicitud.entregada_en)
        self.assertEqual(resultado["pantalla"], "ENTREGA")
        self.assertEqual(resultado["tipo_parada"], "ENTREGA")
        self.asignacion.refresh_from_db()
        self.assertEqual(self.asignacion.estado, EstadoAsignacionSolicitud.ACTIVA)

    def test_reintento_no_duplica_evento_de_llegada(self):
        self._permanencia()
        self.assertIsNotNone(self._detectar())

        self.assertIsNone(self._detectar())

        self.assertEqual(EventoSolicitud.objects.filter(
            solicitud=self.solicitud,
            tipo=TipoEventoSolicitud.LLEGADA_RECOLECCION,
        ).count(), 1)

    def test_un_punto_o_dos_no_confirman_llegada(self):
        self._permanencia(tiempos=(15, 1))
        self._assert_sin_llegada()

    def test_tres_puntos_sin_diez_segundos_no_confirman_llegada(self):
        self._permanencia(tiempos=(8, 4, 1))
        self._assert_sin_llegada()

    def test_diez_segundos_y_precision_maxima_exactos_si_confirman(self):
        self._permanencia(tiempos=(11, 6, 1), precision=Decimal("20"))
        self.assertIsNotNone(self._detectar())

    def test_fechas_repetidas_no_simulan_permanencia(self):
        self._permanencia(tiempos=(1, 1, 1))
        self._assert_sin_llegada()

    def test_un_lote_recien_recibido_no_simula_permanencia_servidor(self):
        self._permanencia(recibido_hace_segundos=0)
        self._assert_sin_llegada()

    def test_gps_fuera_de_radio_no_confirma_llegada(self):
        self._permanencia(ubicacion=self.destino)
        self._assert_sin_llegada()

    def test_precision_deficiente_no_confirma_llegada(self):
        self._permanencia(precision=Decimal("20.01"))
        self._assert_sin_llegada()

    def test_precision_desconocida_no_confirma_llegada(self):
        self._permanencia(precision=None)
        self._assert_sin_llegada()

    def test_capturas_antiguas_no_confirman_llegada(self):
        self._permanencia(tiempos=(50, 40, 31))
        self._assert_sin_llegada()

    def test_recepcion_tardia_de_cola_no_confirma_llegada(self):
        self._permanencia(tiempos=(60, 50, 40), recibido_hace_segundos=0)
        self._assert_sin_llegada()

    def test_capturas_futuras_no_confirman_llegada(self):
        self._permanencia(tiempos=(-1, -8, -15))
        self._assert_sin_llegada()

    def test_punto_intermedio_fuera_del_radio_rompe_racha(self):
        self._punto(20)
        self._punto(15, ubicacion=self.destino)
        self._punto(8)
        self._punto(1)
        self._assert_sin_llegada()

    def test_punto_intermedio_impreciso_rompe_racha(self):
        self._punto(20)
        self._punto(15, precision=None)
        self._punto(8)
        self._punto(1)
        self._assert_sin_llegada()

    def test_puntos_anteriores_al_inicio_de_traslado_no_sirven(self):
        self._preparar_estado(EstadoSolicitud.HACIA_RECOLECCION, hace_segundos=2)
        self._permanencia()
        self._assert_sin_llegada()

    def test_secuencia_con_huecos_no_simula_permanencia_continua(self):
        puntos = self._permanencia()
        sesion = uuid.uuid4()
        for punto, secuencia in zip(puntos, (1, 3, 4)):
            RegistroUbicacion.objects.filter(pk=punto.pk).update(
                sesion_gps=sesion, secuencia=secuencia,
            )
        self._assert_sin_llegada()

    def test_sesion_gps_nueva_no_une_permanencias_anteriores(self):
        puntos = self._permanencia()
        anterior, nueva = uuid.uuid4(), uuid.uuid4()
        for punto, sesion, secuencia in zip(
            puntos, (anterior, nueva, nueva), (1, 1, 2),
        ):
            RegistroUbicacion.objects.filter(pk=punto.pk).update(
                sesion_gps=sesion, secuencia=secuencia,
            )
        self._assert_sin_llegada()

    def test_secuencia_continua_con_permanencia_si_confirma_llegada(self):
        puntos = self._permanencia()
        sesion = uuid.uuid4()
        for secuencia, punto in enumerate(puntos, start=1):
            RegistroUbicacion.objects.filter(pk=punto.pk).update(
                sesion_gps=sesion, secuencia=secuencia,
            )
        self.assertIsNotNone(self._detectar())

    def test_estado_asignada_no_inicia_recorrido_automaticamente(self):
        self._preparar_estado(EstadoSolicitud.ASIGNADA)
        self._permanencia()
        self._assert_sin_llegada()

    def test_estado_recolectada_no_inicia_traslado_automaticamente(self):
        self._preparar_estado(EstadoSolicitud.RECOLECTADA)
        self._permanencia(ubicacion=self.destino)
        self._assert_sin_llegada()

    def test_disponible_tras_reanudar_detecta_llegada_del_traslado_activo(self):
        self._preparar_estado(EstadoSolicitud.EN_TRANSITO)
        self.repartidor.estado_operativo = "AVAILABLE"
        self.repartidor.save(update_fields=("estado_operativo", "actualizado_en"))
        self._permanencia(ubicacion=self.destino)

        llegada = self._detectar()

        self.assertIsNotNone(llegada)
        self.assertEqual(llegada["estado"], EstadoSolicitud.EN_DESTINO)
        self.repartidor.refresh_from_db()
        self.assertEqual(self.repartidor.estado_operativo, "AVAILABLE")

    def test_pausado_no_detecta_llegada_ni_levanta_pausa(self):
        self.repartidor.estado_operativo = "PAUSED"
        self.repartidor.save(update_fields=("estado_operativo", "actualizado_en"))
        self._permanencia()

        self._assert_sin_llegada()
        self.repartidor.refresh_from_db()
        self.assertEqual(self.repartidor.estado_operativo, "PAUSED")

    def test_jornada_finalizada_no_produce_llegada(self):
        self._permanencia()
        self.jornada.estado = EstadoJornada.FINALIZADA
        self.jornada.finalizada_en = self.ahora
        self.jornada.save()
        self._assert_sin_llegada()

    def test_jornada_de_dia_anterior_no_produce_llegada(self):
        self._permanencia()
        self.jornada.iniciada_en = self.ahora - timedelta(days=1)
        self.jornada.save()
        self._assert_sin_llegada()

    def test_solicitud_de_dia_anterior_no_produce_llegada(self):
        self._permanencia()
        Solicitud.objects.filter(pk=self.solicitud.pk).update(
            creado_en=self.ahora - timedelta(days=1),
        )
        self._assert_sin_llegada()

    def test_revocacion_del_rol_impide_llegada(self):
        self._permanencia()
        RolUsuario.objetos.filter(usuario=self.usuario_repartidor).update(
            activo=False, revocado_en=self.ahora, revocado_por=self.administrador,
        )
        self._assert_sin_llegada()

    def test_usuario_ajeno_no_puede_provocar_llegada(self):
        self._permanencia()
        self.assertIsNone(self._detectar(usuario=self.solicitante))
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.HACIA_RECOLECCION)

    @override_settings(LLEGADAS_AUTOMATICAS_HABILITADAS=False)
    def test_interruptor_desactivado_no_cambia_solicitud(self):
        self._permanencia()
        self._assert_sin_llegada()

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_con_rol_global_y_perfil_sin_empresa_detecta_llegada(self):
        RolUsuario.objetos.filter(usuario=self.usuario_repartidor).update(
            activo=False, revocado_en=self.ahora, revocado_por=self.administrador,
        )
        self.usuario_repartidor.empresa = None
        self.usuario_repartidor.save(update_fields=("empresa", "actualizado_en"))
        self.repartidor.vehiculo.empresa = None
        self.repartidor.vehiculo.save(update_fields=("empresa", "actualizado_en"))
        self.repartidor.empresa = None
        self.repartidor.save(update_fields=("empresa", "actualizado_en"))
        RolUsuario.objetos.create(
            usuario=self.usuario_repartidor,
            rol=Rol.objetos.get(codigo="REPARTIDOR_RED"),
            tipo_alcance="GLOBAL",
            asignado_por=self.administrador,
        )
        self._permanencia()

        resultado = self._detectar()

        self.assertIsNotNone(resultado)
        self.assertEqual(resultado["estado"], "AT_PICKUP")
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.EN_RECOLECCION)
        self.assertEqual(self.solicitud.empresa_id, self.empresa.pk)

    def test_configuracion_gps_publica_contrato_completo_de_llegada(self):
        respuesta = self._cliente().get(reverse("seguimiento:configuracion"))

        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertEqual(respuesta.json()["llegada_automatica"], {
            "habilitada": True,
            "radio_metros": 50,
            "permanencia_minima_segundos": 10,
            "minimo_puntos": 3,
            "precision_maxima_metros": 20,
            "antiguedad_maxima_segundos": 30,
            "solo_proxima_parada": True,
            "destino_especial_sin_coordenadas_manual": True,
        })

    def test_no_salta_la_primera_parada_para_llegar_a_otro_envio(self):
        segunda = Solicitud.objects.create(
            cantidad_tubos=1,
            numero=f"SOL-LLEGADA-{uuid.uuid4().hex[:8]}",
            empresa=self.empresa,
            solicitada_por=self.solicitante,
            repartidor_asignado=self.repartidor,
            prioridad="NORMAL",
            tipo_servicio=self.tipo_servicio,
            origen=self.destino,
            destino=self.origen,
            estado=EstadoSolicitud.HACIA_RECOLECCION,
            asignada_en=self.ahora - timedelta(minutes=1),
        )
        AsignacionSolicitud.objects.create(
            solicitud=segunda,
            repartidor=self.repartidor,
            asignada_por=self.administrador,
            estado=EstadoAsignacionSolicitud.ACTIVA,
            asignada_en=segunda.asignada_en,
            aceptada_en=self.ahora - timedelta(seconds=50),
        )
        self._permanencia(ubicacion=self.destino)

        self._assert_sin_llegada()
        segunda.refresh_from_db()
        self.assertEqual(segunda.estado, EstadoSolicitud.HACIA_RECOLECCION)

    def test_recoleccion_especial_con_coordenadas_si_detecta_llegada(self):
        self.solicitud.modalidad = ModalidadSolicitud.ESPECIAL
        self.solicitud.destino = None
        self.solicitud.destino_especial = "Encargo especial sin destino geocodificado"
        self.solicitud.save()
        self._permanencia()

        self.assertIsNotNone(self._detectar())
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.EN_RECOLECCION)

    def test_destino_especial_sin_coordenadas_conserva_llegada_manual(self):
        self.solicitud.modalidad = ModalidadSolicitud.ESPECIAL
        self.solicitud.destino = None
        self.solicitud.destino_especial = "Encargo sin coordenadas"
        self.solicitud.save()
        self._preparar_estado(EstadoSolicitud.EN_TRANSITO)
        self._permanencia()
        self._assert_sin_llegada()

        respuesta = self._cliente().post(
            reverse("solicitudes:transicion", kwargs={"solicitud_id": self.solicitud.pk}),
            {"estado_destino": EstadoSolicitud.EN_DESTINO},
            format="json",
        )

        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.EN_DESTINO)

    def test_llegada_manual_a_recoleccion_con_gps_no_es_aceptada(self):
        respuesta = self._cliente().post(
            reverse("solicitudes:transicion", kwargs={"solicitud_id": self.solicitud.pk}),
            {"estado_destino": EstadoSolicitud.EN_RECOLECCION},
            format="json",
        )

        self.assertEqual(respuesta.status_code, 400, respuesta.data)
        self.assertIn("estado_destino", respuesta.data)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.HACIA_RECOLECCION)

    def test_llegada_manual_a_destino_con_gps_no_es_aceptada(self):
        self._preparar_estado(EstadoSolicitud.EN_TRANSITO)
        respuesta = self._cliente().post(
            reverse("solicitudes:transicion", kwargs={"solicitud_id": self.solicitud.pk}),
            {"estado_destino": EstadoSolicitud.EN_DESTINO},
            format="json",
        )
        self.assertEqual(respuesta.status_code, 400, respuesta.data)
        self.assertIn("estado_destino", respuesta.data)

    def test_json_del_cliente_no_puede_falsificar_prueba_interna_gps(self):
        respuesta = self._cliente().post(
            reverse("solicitudes:transicion", kwargs={"solicitud_id": self.solicitud.pk}),
            {
                "estado_destino": EstadoSolicitud.EN_RECOLECCION,
                "llegada_gps": {
                    "cantidad_puntos": 3,
                    "permanencia_captura_segundos": 15,
                    "permanencia_servidor_segundos": 15,
                },
            },
            format="json",
        )
        self.assertEqual(respuesta.status_code, 400, respuesta.data)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.HACIA_RECOLECCION)

    def test_tras_llegada_aun_exige_foto_para_recolectar(self):
        self._permanencia()
        self.assertIsNotNone(self._detectar())

        with self.assertRaises(ValidationError) as contexto:
            cambiar_estado_solicitud(
                self.usuario_repartidor,
                self.solicitud.pk,
                {"estado_destino": EstadoSolicitud.RECOLECTADA},
            )

        self.assertIn("evidencia", contexto.exception.detail)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.EN_RECOLECCION)

    def test_tras_llegada_aun_exige_foto_para_entregar(self):
        self._preparar_estado(EstadoSolicitud.EN_TRANSITO)
        self._permanencia(ubicacion=self.destino)
        self.assertIsNotNone(self._detectar())

        with self.assertRaises(ValidationError) as contexto:
            cambiar_estado_solicitud(
                self.usuario_repartidor,
                self.solicitud.pk,
                {"estado_destino": EstadoSolicitud.ENTREGADA},
            )

        self.assertIn("evidencia", contexto.exception.detail)

    def test_mi_ruta_recupera_llegada_si_respuesta_gps_se_perdio(self):
        self._permanencia()
        resultado = self._detectar()

        respuesta = self._cliente().get(reverse("rutas:mi-ruta"))

        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertEqual(respuesta.data["llegada_actual"]["evento_id"], resultado["evento_id"])
        self.assertEqual(respuesta.data["llegada_actual"]["pantalla"], "RECOLECCION")

    def test_mi_ruta_sin_llegada_devuelve_null(self):
        respuesta = self._cliente().get(reverse("rutas:mi-ruta"))
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertIsNone(respuesta.data["llegada_actual"])

    def test_ingesta_programa_llegada_tras_commit_y_reintento_no_duplica(self):
        self._punto(15)
        self._punto(8)
        datos = {
            "jornada_id": self.jornada.pk,
            "registros": [{
                "id_cliente": uuid.uuid4(),
                "latitud": self.origen.latitud,
                "longitud": self.origen.longitud,
                "precision_metros": Decimal("8"),
                "registrada_en": self.ahora - timedelta(seconds=1),
            }],
        }
        with self.captureOnCommitCallbacks(execute=True):
            resultado = registrar_ubicaciones(self.usuario_repartidor, datos)
            self.solicitud.refresh_from_db()
            self.assertEqual(self.solicitud.estado, EstadoSolicitud.HACIA_RECOLECCION)

        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.EN_RECOLECCION)
        self.assertEqual(len(resultado["llegadas_detectadas"]), 1)
        with self.captureOnCommitCallbacks(execute=True):
            repetido = registrar_ubicaciones(self.usuario_repartidor, datos)
        self.assertEqual(repetido["creados"], 0)
        self.assertEqual(EventoSolicitud.objects.filter(
            solicitud=self.solicitud,
            tipo=TipoEventoSolicitud.LLEGADA_RECOLECCION,
        ).count(), 1)

    def test_api_ingesta_incluye_lista_aditiva_de_llegadas(self):
        respuesta = self._cliente().post(
            reverse("seguimiento:registros"),
            {
                "jornada_id": str(self.jornada.pk),
                "registros": [{
                    "id_cliente": str(uuid.uuid4()),
                    "latitud": str(self.origen.latitud),
                    "longitud": str(self.origen.longitud),
                    "precision_metros": "8",
                    "registrada_en": (self.ahora - timedelta(seconds=1)).isoformat(),
                }],
            },
            format="json",
        )
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        self.assertEqual(respuesta.data["creados"], 1)
        self.assertEqual(respuesta.data["llegadas_detectadas"], [])


@override_settings(
    MODO_APLICACION="CORPORATIVO",
    PROVEEDOR_AUTENTICACION="LOCAL",
    LLEGADAS_AUTOMATICAS_HABILITADAS=True,
    RADIO_LLEGADA_METROS=50,
    PERMANENCIA_LLEGADA_SEGUNDOS=10,
    MINIMO_PUNTOS_LLEGADA=3,
    PRECISION_LLEGADA_MAXIMA_METROS=20,
    ANTIGUEDAD_LLEGADA_MAXIMA_SEGUNDOS=30,
)
class PruebasHTTPCommitLlegadas(TransactionTestCase):
    """El commit real termina antes de serializar la respuesta HTTP del lote."""

    serialized_rollback = True
    _preparar_estado = PruebasLlegadasAutomaticas._preparar_estado
    _punto = PruebasLlegadasAutomaticas._punto
    _cliente = PruebasLlegadasAutomaticas._cliente

    def setUp(self):
        datos_seguimiento.PruebasSeguimiento.setUpTestData.__func__(type(self))
        PruebasLlegadasAutomaticas.setUp(self)
        self._punto(15)
        self._punto(8)
        self.datos = {
            "jornada_id": str(self.jornada.pk),
            "registros": [{
                "id_cliente": str(uuid.uuid4()),
                "latitud": str(self.origen.latitud),
                "longitud": str(self.origen.longitud),
                "precision_metros": "8",
                "registrada_en": (self.ahora - timedelta(seconds=1)).isoformat(),
            }],
        }

    def test_http_real_serializa_llegada_confirmada_tras_commit(self):
        self.assertFalse(connection.in_atomic_block)

        respuesta = self._cliente().post(
            reverse("seguimiento:registros"), self.datos, format="json",
        )

        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        cuerpo = respuesta.json()
        self.assertEqual(len(cuerpo["llegadas_detectadas"]), 1)
        llegada = cuerpo["llegadas_detectadas"][0]
        self.assertEqual(llegada["estado"], "AT_PICKUP")
        self.assertEqual(llegada["solicitud_id"], str(self.solicitud.pk))
        self.assertIsNotNone(parse_datetime(llegada["detectada_en"]))
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.EN_RECOLECCION)
        self.assertTrue(EventoSolicitud.objects.filter(pk=llegada["evento_id"]).exists())

    def test_fallo_detector_no_rompe_http_y_reintento_identico_recupera(self):
        with (
            patch(
                "apps.seguimiento.llegadas.detectar_llegada",
                side_effect=RuntimeError("Fallo transitorio simulado de detector."),
            ),
            self.assertLogs("django.db.backends.base", level="ERROR"),
        ):
            respuesta = self._cliente().post(
                reverse("seguimiento:registros"), self.datos, format="json",
            )

        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        self.assertEqual(respuesta.json()["llegadas_detectadas"], [])
        self.assertTrue(RegistroUbicacion.objects.filter(
            id_cliente=self.datos["registros"][0]["id_cliente"],
        ).exists())
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.HACIA_RECOLECCION)

        repetido = self._cliente().post(
            reverse("seguimiento:registros"), self.datos, format="json",
        )

        self.assertEqual(repetido.status_code, 201, repetido.data)
        self.assertEqual(repetido.json()["creados"], 0)
        self.assertEqual(repetido.json()["repetidos"], 1)
        self.assertEqual(len(repetido.json()["llegadas_detectadas"]), 1)
        self.assertEqual(EventoSolicitud.objects.filter(
            solicitud=self.solicitud,
            tipo=TipoEventoSolicitud.LLEGADA_RECOLECCION,
        ).count(), 1)
