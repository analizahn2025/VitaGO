import re

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.urls import reverse


class PruebasRendimientoAPI(SimpleTestCase):
    @override_settings(
        REGISTRAR_RENDIMIENTO_API=True,
        UMBRAL_API_LENTA_MS=1000,
    )
    def test_informa_tiempo_sin_cambiar_respuesta(self):
        with self.assertLogs("vitago.api", level="INFO") as registros:
            respuesta = self.client.get(reverse("nucleo:salud"))

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            respuesta.json(),
            {
                "estado": "correcto",
                "servicio": settings.NOMBRE_APLICACION,
            },
        )
        self.assertRegex(
            respuesta["Server-Timing"],
            re.compile(r"^aplicacion;dur=\d+\.\d{2}$"),
        )
        self.assertIn(
            "API GET /api/v1/salud/ 200",
            registros.output[0],
        )

    @override_settings(
        REGISTRAR_RENDIMIENTO_API=False,
        UMBRAL_API_LENTA_MS=0,
    )
    def test_advierte_cuando_una_api_supera_el_umbral(self):
        with self.assertLogs("vitago.api", level="WARNING") as registros:
            respuesta = self.client.get(reverse("nucleo:salud"))

        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("WARNING:vitago.api:API GET", registros.output[0])
