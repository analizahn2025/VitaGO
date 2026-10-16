"""Validación estructural y decodificación sin usar archivos de desarrollo."""

from io import BytesIO
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from PIL import Image
from rest_framework.exceptions import ValidationError

from apps.evidencias.servicios import validar_archivo_imagen
from apps.nucleo.tests.imagenes import crear_imagen_prueba


class PruebasValidacionImagenes(SimpleTestCase):
    def test_acepta_fotos_validas_y_conserva_original_y_posicion(self):
        for formato, esperado in (("PNG", ("image/png", "png")), ("JPEG", ("image/jpeg", "jpg")), ("WEBP", ("image/webp", "webp"))):
            with self.subTest(formato=formato):
                archivo = crear_imagen_prueba(formato)
                original = archivo.read()
                archivo.seek(2)
                self.assertEqual(validar_archivo_imagen(archivo), esperado)
                self.assertEqual(archivo.tell(), 2)
                archivo.seek(0)
                self.assertEqual(archivo.read(), original)

    def test_rechaza_firmas_sin_imagen_real(self):
        for tipo, firma in (("image/png", b"\x89PNG\r\n\x1a\n"), ("image/jpeg", b"\xff\xd8\xff"), ("image/webp", b"RIFF0000WEBP")):
            with self.subTest(tipo=tipo):
                archivo = SimpleUploadedFile("corrupta", firma + b"\x00" * 32, content_type=tipo)
                with self.assertRaises(ValidationError) as error:
                    validar_archivo_imagen(archivo)
                self.assertIn("archivo", error.exception.detail)

    def test_rechaza_archivos_truncados(self):
        for formato in ("PNG", "JPEG", "WEBP"):
            with self.subTest(formato=formato):
                valido = crear_imagen_prueba(formato)
                archivo = SimpleUploadedFile(valido.name, valido.read()[:-12], content_type=valido.content_type)
                with self.assertRaises(ValidationError):
                    validar_archivo_imagen(archivo)

    def test_rechaza_mime_distinto_al_formato_real(self):
        archivo = crear_imagen_prueba("PNG")
        archivo.content_type = "image/jpeg"
        with self.assertRaises(ValidationError) as error:
            validar_archivo_imagen(archivo)
        self.assertIn("archivo", error.exception.detail)

    @override_settings(PIXELES_MAXIMOS_EVIDENCIA=15)
    def test_limita_dimensiones_antes_de_decodificar(self):
        archivo = crear_imagen_prueba(tamano=(4, 4))
        with patch("PIL.Image.Image.load") as cargar:
            with self.assertRaises(ValidationError):
                validar_archivo_imagen(archivo)
            cargar.assert_not_called()

    def test_rechaza_bombas_y_advertencias_de_descompresion(self):
        for maximo in (4, 10):
            archivo = crear_imagen_prueba(tamano=(4, 4))
            with self.subTest(maximo=maximo), patch.object(Image, "MAX_IMAGE_PIXELS", maximo):
                with self.assertRaises(ValidationError):
                    validar_archivo_imagen(archivo)

    def test_rechaza_animaciones(self):
        contenido = BytesIO()
        with Image.new("RGB", (4, 4), "red") as primera, Image.new("RGB", (4, 4), "blue") as segunda:
            primera.save(contenido, format="PNG", save_all=True, append_images=[segunda], duration=100)
        archivo = SimpleUploadedFile("animacion.png", contenido.getvalue(), content_type="image/png")
        with self.assertRaises(ValidationError):
            validar_archivo_imagen(archivo)

    @override_settings(TAMANO_MAXIMO_EVIDENCIA_MB=1)
    def test_conserva_limite_de_tamano(self):
        archivo = SimpleUploadedFile("grande.png", b"x" * (1024 * 1024 + 1), content_type="image/png")
        with self.assertRaises(ValidationError):
            validar_archivo_imagen(archivo)
