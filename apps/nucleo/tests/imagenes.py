"""Fotografías sintéticas válidas, generadas en memoria para las pruebas."""

from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image


def crear_imagen_prueba(formato="PNG", *, nombre=None, tamano=(4, 4)):
    contenido = BytesIO()
    with Image.new("RGB", tamano, color=(20, 80, 120)) as imagen:
        imagen.save(contenido, format=formato)
    extension, tipo = {
        "PNG": ("png", "image/png"),
        "JPEG": ("jpg", "image/jpeg"),
        "WEBP": ("webp", "image/webp"),
    }[formato]
    return SimpleUploadedFile(nombre or f"prueba.{extension}", contenido.getvalue(), content_type=tipo)
