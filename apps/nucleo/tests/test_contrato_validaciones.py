from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError
from rest_framework.views import exception_handler

from apps.flota.serializadores import SerializadorCreacionVehiculo
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

    def test_error_conserva_nombre_del_campo_de_recipiente(self):
        respuesta = exception_handler(
            ValidationError(
                {"cantidad_frascos": "Debe indicar una cantidad válida."}
            ),
            {},
        )
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("cantidad_frascos", respuesta.data)
