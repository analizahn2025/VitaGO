from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from apps.ubicaciones.opciones import EstadoUbicacionEmpresa
from apps.ubicaciones.models import Ubicacion, UbicacionEmpresa


class PruebasModeloUbicacion(SimpleTestCase):
    def test_validador_latitud_rechaza_valor_mayor_a_noventa(self):
        campo = Ubicacion._meta.get_field("latitud")

        with self.assertRaises(ValidationError):
            campo.run_validators(Decimal("90.000001"))

    def test_validador_longitud_rechaza_valor_menor_a_menos_ciento_ochenta(self):
        campo = Ubicacion._meta.get_field("longitud")

        with self.assertRaises(ValidationError):
            campo.run_validators(Decimal("-180.000001"))

    def test_ubicacion_empresa_esta_pendiente_por_defecto(self):
        ubicacion_empresa = UbicacionEmpresa()

        self.assertEqual(
            ubicacion_empresa.estado,
            EstadoUbicacionEmpresa.PENDIENTE,
        )
