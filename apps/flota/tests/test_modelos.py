from django.test import SimpleTestCase

from apps.flota.models import Vehiculo


class PruebasModeloVehiculo(SimpleTestCase):
    def test_normaliza_placa(self):
        vehiculo = Vehiculo(placa=" hba-1234 ", tipo="MOTOCICLETA")

        vehiculo.clean()

        self.assertEqual(vehiculo.placa, "HBA-1234")
