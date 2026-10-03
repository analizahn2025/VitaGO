from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.ejecucion import (
    ProveedorAutenticacion,
    interpretar_proveedor_autenticacion,
)


class PruebasProveedorAutenticacion(SimpleTestCase):
    def test_normaliza_proveedor_local(self):
        resultado = interpretar_proveedor_autenticacion(" local ")

        self.assertEqual(resultado, ProveedorAutenticacion.LOCAL)

    def test_rechaza_proveedor_desconocido(self):
        with self.assertRaises(ImproperlyConfigured):
            interpretar_proveedor_autenticacion("desconocido")
