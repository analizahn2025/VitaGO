from importlib import import_module

from django.test import SimpleTestCase


catalogo = import_module(
    "apps.ubicaciones.migrations.0002_catalogo_tipos_ubicacion"
)


class PruebasCatalogoTiposUbicacion(SimpleTestCase):
    def test_contiene_los_tipos_iniciales_esperados(self):
        self.assertEqual(len(catalogo.TIPOS_UBICACION), 12)
        self.assertIn("HOSPITAL", catalogo.TIPOS_UBICACION)
        self.assertIn("LABORATORIO_CLINICO", catalogo.TIPOS_UBICACION)
        self.assertIn("SUCURSAL", catalogo.TIPOS_UBICACION)
        self.assertIn("OTRO", catalogo.TIPOS_UBICACION)

    def test_codigos_y_nombres_no_estan_vacios(self):
        for codigo, nombre in catalogo.TIPOS_UBICACION.items():
            self.assertEqual(codigo, codigo.strip().upper())
            self.assertTrue(nombre.strip())
