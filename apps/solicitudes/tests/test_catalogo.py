from importlib import import_module

from django.test import SimpleTestCase


catalogo = import_module(
    "apps.solicitudes.migrations.0002_catalogo_tipos_servicio"
)


class PruebasCatalogoTiposServicio(SimpleTestCase):
    def test_contiene_los_nueve_tipos_iniciales(self):
        self.assertEqual(len(catalogo.TIPOS_SERVICIO), 9)
        self.assertIn("MUESTRA_BIOLOGICA", catalogo.TIPOS_SERVICIO)
        self.assertIn("MEDICAMENTO", catalogo.TIPOS_SERVICIO)
        self.assertIn("OTRO", catalogo.TIPOS_SERVICIO)

    def test_catalogo_usa_codigos_y_nombres_en_espanol(self):
        for codigo, (nombre, descripcion) in catalogo.TIPOS_SERVICIO.items():
            self.assertEqual(codigo, codigo.strip().upper())
            self.assertTrue(nombre.strip())
            self.assertTrue(descripcion.strip())
