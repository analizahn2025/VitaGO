"""Un traspaso con paquete exige la llegada del nuevo motorista al destino."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.jornadas.models import JornadaRepartidor
from apps.repartidores.models import Repartidor
from apps.rutas.selectores import obtener_paradas_operativas
from apps.seguimiento.llegadas import detectar_llegada
from apps.seguimiento.models import RegistroUbicacion
from apps.solicitudes.models import EventoSolicitud
from apps.solicitudes.opciones import EstadoSolicitud, TipoEventoSolicitud
from apps.solicitudes.servicios import reintentar_solicitudes_pendientes
from apps.solicitudes.tests import test_contingencias as datos_contingencias


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
class PruebasLlegadaTrasTraspaso(TestCase):
    setUpTestData = classmethod(
        datos_contingencias.PruebasContingenciasCorporativas.setUpTestData.__func__
    )
    _registrar_gps = datos_contingencias.PruebasContingenciasCorporativas._registrar_gps
    _asignar = datos_contingencias.PruebasContingenciasCorporativas._asignar
    _suspender = datos_contingencias.PruebasContingenciasCorporativas._suspender

    def setUp(self):
        datos_contingencias.PruebasContingenciasCorporativas.setUp(self)
        bloqueo_google = patch(
            "apps.rutas.proveedor_google.urlopen",
            side_effect=AssertionError("El traspaso y la llegada no consultan a Google."),
        )
        bloqueo_google.start()
        self.addCleanup(bloqueo_google.stop)
        self.cliente = APIClient()
        self.cliente.force_authenticate(self.nuevo.usuario)

    def _preparar_llegada_anterior(self, *, especial=False):
        self.asignacion_anterior = self._asignar(
            EstadoSolicitud.EN_DESTINO, especial=especial,
        )
        self.recogida = self.solicitud.recolectada_en
        self.fecha_anterior = self.ahora - timedelta(seconds=90)
        self.solicitud.llegada_destino_en = self.fecha_anterior
        self.solicitud.save(update_fields=("llegada_destino_en", "actualizado_en"))
        self.evento_anterior = EventoSolicitud.objects.create(
            solicitud=self.solicitud,
            repartidor=self.anterior,
            realizado_por=self.anterior.usuario,
            tipo=TipoEventoSolicitud.LLEGADA_DESTINO,
            latitud=self.destino.latitud,
            longitud=self.destino.longitud,
            metadatos={
                "estado_anterior": EstadoSolicitud.EN_TRANSITO,
                "estado_nuevo": EstadoSolicitud.EN_DESTINO,
            },
        )
        EventoSolicitud.objects.filter(pk=self.evento_anterior.pk).update(
            creado_en=self.fecha_anterior,
        )

    def _assert_traspaso_pendiente_de_llegada(self, *, especial=False):
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.repartidor_asignado_id, self.nuevo.pk)
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.EN_TRANSITO)
        self.assertIsNone(self.solicitud.llegada_destino_en)
        self.assertEqual(self.solicitud.recolectada_en, self.recogida)
        self.assertFalse(self.solicitud.reasignacion_pendiente)
        self.assertEqual(
            [parada["tipo"] for parada in obtener_paradas_operativas(self.nuevo)],
            ["ENVIO_ESPECIAL" if especial else "ENTREGA"],
        )
        self.assertEqual(obtener_paradas_operativas(self.anterior), [])
        self.asignacion_anterior.refresh_from_db()
        self.assertEqual(self.asignacion_anterior.estado, "REASIGNADA")
        self.evento_anterior.refresh_from_db()
        self.assertEqual(self.evento_anterior.creado_en, self.fecha_anterior)
        self.assertEqual(self.evento_anterior.repartidor_id, self.anterior.pk)
        self.assertEqual(self.evento_anterior.tipo, TipoEventoSolicitud.LLEGADA_DESTINO)
        self.assertFalse(self.solicitud.eventos.filter(
            repartidor=self.nuevo, tipo=TipoEventoSolicitud.LLEGADA_DESTINO,
        ).exists())
        reasignacion = self.solicitud.eventos.filter(
            tipo=TipoEventoSolicitud.REASIGNADA, repartidor=self.nuevo,
        ).latest("creado_en")
        self.assertEqual(reasignacion.metadatos["estado_anterior"], EstadoSolicitud.EN_DESTINO)
        self.assertEqual(reasignacion.metadatos["estado_nuevo"], EstadoSolicitud.EN_TRANSITO)
        respuesta = self.cliente.get(reverse("rutas:mi-ruta"))
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertIsNone(respuesta.data["llegada_actual"])

    def _detectar_llegada_propia(self):
        asignacion = self.solicitud.asignaciones.get(estado="ACTIVA")
        jornada = JornadaRepartidor.objects.get(repartidor=self.nuevo, estado="ACTIVA")
        ahora = asignacion.asignada_en + timedelta(seconds=30)
        sesion = uuid4()
        for secuencia, retraso in enumerate((20, 10, 0), start=1):
            capturada_en = ahora - timedelta(seconds=retraso)
            punto = RegistroUbicacion.objects.create(
                id_cliente=uuid4(), sesion_gps=sesion, secuencia=secuencia,
                repartidor=self.nuevo, jornada=jornada,
                latitud=self.destino.latitud, longitud=self.destino.longitud,
                precision_metros=Decimal("5"), registrada_en=capturada_en,
                es_operativo=True,
            )
            RegistroUbicacion.objects.filter(pk=punto.pk).update(creado_en=capturada_en)
        with patch("apps.seguimiento.llegadas.timezone.now", return_value=ahora):
            llegada = detectar_llegada(self.nuevo.usuario, self.nuevo.pk, jornada.pk)
        self.assertIsNotNone(llegada)
        self.assertNotEqual(llegada["evento_id"], str(self.evento_anterior.pk))
        self.assertEqual(llegada["fuente"], "GPS")
        self._assert_llegada_propia(llegada["evento_id"])

    def _assert_llegada_propia(self, evento_id):
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.EN_DESTINO)
        self.assertIsNotNone(self.solicitud.llegada_destino_en)
        self.assertEqual(self.solicitud.recolectada_en, self.recogida)
        self.assertEqual(self.solicitud.eventos.filter(
            tipo=TipoEventoSolicitud.LLEGADA_DESTINO,
        ).count(), 2)
        self.assertEqual(
            self.solicitud.eventos.get(pk=evento_id).repartidor_id, self.nuevo.pk,
        )
        respuesta = self.cliente.get(reverse("rutas:mi-ruta"))
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertEqual(str(respuesta.data["llegada_actual"]["evento_id"]), str(evento_id))

    def test_traspaso_normal_invalida_llegada_anterior_y_detecta_la_propia(self):
        self._preparar_llegada_anterior()
        self._suspender()
        self._assert_traspaso_pendiente_de_llegada()
        self._detectar_llegada_propia()

    def test_traspaso_especial_invalida_llegada_y_permite_confirmacion_manual_propia(self):
        self._preparar_llegada_anterior(especial=True)
        self._suspender()
        self._assert_traspaso_pendiente_de_llegada(especial=True)
        respuesta = self.cliente.post(
            reverse("solicitudes:transicion", args=[self.solicitud.pk]),
            {"estado_destino": EstadoSolicitud.EN_DESTINO}, format="json",
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        evento = self.solicitud.eventos.get(
            tipo=TipoEventoSolicitud.LLEGADA_DESTINO, repartidor=self.nuevo,
        )
        self._assert_llegada_propia(evento.pk)

    def test_traspaso_diferido_tambien_exige_llegada_del_reemplazo(self):
        self._preparar_llegada_anterior()
        Repartidor.objects.filter(pk=self.nuevo.pk).update(estado_operativo="PAUSED")
        self._suspender()
        self.assertIsNone(self.solicitud.repartidor_asignado_id)
        self.assertTrue(self.solicitud.reasignacion_pendiente)
        Repartidor.objects.filter(pk=self.nuevo.pk).update(estado_operativo="AVAILABLE")
        self.assertEqual(reintentar_solicitudes_pendientes(self.empresa.pk), 1)
        self._assert_traspaso_pendiente_de_llegada()
        self._detectar_llegada_propia()

    def test_gps_del_nuevo_anterior_al_traspaso_no_cuenta_como_llegada(self):
        self._preparar_llegada_anterior()
        jornada = JornadaRepartidor.objects.get(repartidor=self.nuevo, estado="ACTIVA")
        for retraso in (20, 10, 0):
            fecha = self.ahora - timedelta(seconds=retraso)
            punto = RegistroUbicacion.objects.create(
                id_cliente=uuid4(), repartidor=self.nuevo, jornada=jornada,
                latitud=self.destino.latitud, longitud=self.destino.longitud,
                precision_metros=Decimal("5"), registrada_en=fecha,
            )
            RegistroUbicacion.objects.filter(pk=punto.pk).update(creado_en=fecha)
        self._suspender()
        self._assert_traspaso_pendiente_de_llegada()
        self.assertIsNone(detectar_llegada(self.nuevo.usuario, self.nuevo.pk, jornada.pk))
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.EN_TRANSITO)
