from django.test import SimpleTestCase

from apps.repartidores.serializadores import (
    SerializadorActualizacionOperacionRepartidor,
)


class PruebasSerializadoresRepartidores(SimpleTestCase):
    def test_operacion_requiere_un_cambio(self):
        serializador = SerializadorActualizacionOperacionRepartidor(
            data={"motivo": "Sin cambios"}
        )

        self.assertFalse(serializador.is_valid())
        self.assertIn("estado_operativo", serializador.errors)

    def test_operacion_rechaza_capacidad_manual(self):
        serializador = SerializadorActualizacionOperacionRepartidor(
            data={
                "estado_operativo": "AVAILABLE",
                "capacidad": "AVAILABLE_SPACE",
            }
        )

        self.assertFalse(serializador.is_valid())
        self.assertIn("capacidad", serializador.errors)
