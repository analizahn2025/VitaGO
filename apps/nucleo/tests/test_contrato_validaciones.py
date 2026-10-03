from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.flota.serializadores import SerializadorCreacionVehiculo
from apps.nucleo.excepciones import manejador_excepciones
from apps.repartidores.serializadores import SerializadorActualizacionOperacionRepartidor


class PruebasContratoValidaciones(SimpleTestCase):
    def test_solo_motocicletas_y_sin_capacidad_de_carga(self):
        datos = {"placa": "PRU-001", "tipo": "AUTOMOVIL"}
        serializador = SerializadorCreacionVehiculo(data=datos)
        self.assertFalse(serializador.is_valid())
        self.assertIn("tipo", serializador.errors)

        datos["tipo"] = "MOTOCICLETA"
        datos["capacidad_carga_kg"] = "25.00"
        serializador = SerializadorCreacionVehiculo(data=datos)
        self.assertFalse(serializador.is_valid())
        self.assertIn("capacidad_carga_kg", serializador.errors)

    def test_capacidad_manual_no_es_editable(self):
        serializador = SerializadorActualizacionOperacionRepartidor(
            data={"estado_operativo": "AVAILABLE", "capacidad": "FULL"}
        )
        self.assertFalse(serializador.is_valid())
        self.assertIn("capacidad", serializador.errors)

    def test_error_articulo_incluye_indice_y_campo(self):
        respuesta = manejador_excepciones(
            ValidationError(
                {"articulos": [{}, {"cantidad": ["Debe ser positiva."]}]}
            ),
            {},
        )
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(respuesta.data["articulos"][0]["indice"], 1)
        self.assertEqual(respuesta.data["articulos"][0]["campo"], "cantidad")
