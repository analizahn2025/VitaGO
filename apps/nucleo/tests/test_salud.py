from django.test import SimpleTestCase
from django.urls import reverse


class PruebasSalud(SimpleTestCase):
    def test_endpoint_es_publico_e_informa_estado_del_servicio(self):
        respuesta = self.client.get(reverse("nucleo:salud"))

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            respuesta.json(),
            {
                "estado": "correcto",
                "servicio": "VitaGo",
            },
        )
