"""Temperatura manual por recolección, evidencia atómica y fuente confiable."""

from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.evidencias.models import EvidenciaSolicitud
from apps.evidencias.servicios import registrar_evidencia
from apps.evidencias.tests import test_operacion as datos
from apps.solicitudes.models import EventoSolicitud, Solicitud
from apps.solicitudes.servicios import cambiar_estado_solicitud


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasTemperaturaRecoleccion(TestCase):
    setUpTestData = classmethod(datos.PruebasOperacionConEvidencias.setUpTestData.__func__)
    _archivo_png = datos.PruebasOperacionConEvidencias._archivo_png

    def setUp(self):
        datos.PruebasOperacionConEvidencias.setUp(self)
        Solicitud.objects.filter(pk=self.solicitud.pk).update(estado="AT_PICKUP")
        self.cliente = APIClient(); self.cliente.force_authenticate(self.usuario_repartidor)
        self.url = reverse("solicitudes:evidencias:lista-registro", args=[self.solicitud.pk])
        self.enterContext(patch("apps.rutas.proveedor_google.urlopen", side_effect=AssertionError("Sin Google real")))

    def _datos(self, **cambios):
        return {"tipo": "FOTO_RECOLECCION", "archivo": self._archivo_png(),
                "latitud": "14.072300", "longitud": "-87.192100", **cambios}

    def test_sin_temperatura_no_guarda_foto_ni_recoge(self):
        respuesta = self.cliente.post(self.url, self._datos(), format="multipart")
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("temperatura_contenedor_c", respuesta.data)
        self.assertFalse(EvidenciaSolicitud.objects.exists())
        self.solicitud.refresh_from_db(); self.assertEqual(self.solicitud.estado, "AT_PICKUP")

    def test_temperatura_manual_con_hora_del_servidor_y_auditoria(self):
        ahora = timezone.now()
        with patch("apps.evidencias.servicios.timezone.now", return_value=ahora):
            r = self.cliente.post(self.url, self._datos(temperatura_contenedor_c="4.50", capturada_en="2000-01-01"), format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["temperatura_contenedor_c"], r.data["fuente_temperatura"]), ("4.50", "MANUAL"))
        evidencia = EvidenciaSolicitud.objects.get()
        self.assertEqual(evidencia.capturada_en, ahora)
        evento = EventoSolicitud.objects.get(tipo="EVIDENCIA_REGISTRADA")
        self.assertEqual(evento.metadatos["temperatura_contenedor_c"], "4.50")

    def test_servicio_no_permite_omitir_temperatura(self):
        with self.assertRaises(ValidationError) as error:
            registrar_evidencia(self.usuario_repartidor, self.solicitud.pk, self._datos())
        self.assertIn("temperatura_contenedor_c", error.exception.detail)

    def test_numeros_no_finitos_precision_y_texto_se_rechazan(self):
        for valor in ("NaN", "Infinity", "-Infinity", "abc", "4.555", "1E999"):
            with self.subTest(valor=valor), self.assertRaises(ValidationError):
                registrar_evidencia(self.usuario_repartidor, self.solicitud.pk, self._datos(temperatura_contenedor_c=valor))
        self.assertFalse(EvidenciaSolicitud.objects.exists())

    def test_cliente_no_puede_simular_un_sensor(self):
        r = self.cliente.post(self.url, self._datos(temperatura_contenedor_c="4.5", fuente_temperatura="AUTOMATICA"), format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertIn("fuente_temperatura", r.data)

    def test_foto_historica_sin_temperatura_no_acredita_una_recoleccion_nueva(self):
        EvidenciaSolicitud.objects.create(solicitud=self.solicitud, repartidor=self.repartidor,
            tipo="FOTO_RECOLECCION", clave_almacenamiento="historico/sin-temperatura.png",
            tipo_contenido="image/png", tamano_bytes=100, latitud="14", longitud="-87", capturada_en=timezone.now())
        with self.assertRaises(ValidationError):
            cambiar_estado_solicitud(self.usuario_repartidor, self.solicitud.pk, {"estado_destino": "PICKED_UP"})

    def test_fallo_de_estado_revierte_temperatura_foto_y_evento(self):
        with patch("apps.solicitudes.servicios.cambiar_estado_solicitud", side_effect=ValidationError({"estado_destino": "Fallo"})):
            with self.assertRaises(ValidationError):
                registrar_evidencia(self.usuario_repartidor, self.solicitud.pk, self._datos(temperatura_contenedor_c="4.50"))
        self.assertFalse(EvidenciaSolicitud.objects.exists())
        self.assertFalse(EventoSolicitud.objects.exists())

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_tambien_exige_temperatura(self):
        self.test_sin_temperatura_no_guarda_foto_ni_recoge()

    def test_no_se_registra_otra_temperatura_en_foto_de_entrega(self):
        Solicitud.objects.filter(pk=self.solicitud.pk).update(estado="AT_DESTINATION")
        r = self.cliente.post(self.url, self._datos(tipo="FOTO_ENTREGA", temperatura_contenedor_c="4.50"), format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertIn("temperatura_contenedor_c", r.data)
