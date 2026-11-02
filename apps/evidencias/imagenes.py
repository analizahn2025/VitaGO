"""Imágenes privadas en PostgreSQL; el contrato HTTP sigue entregando archivos."""

import base64
import binascii
from datetime import datetime
from io import BytesIO

from django.core.files.storage import default_storage
from django.core.exceptions import SuspiciousFileOperation
from django.db import models
from django.http import FileResponse, Http404
from django.utils import timezone
from rest_framework.exceptions import APIException


def inicio_mes(fecha, desplazamiento=0):
    local = fecha.astimezone(timezone.get_default_timezone())
    meses = local.year * 12 + local.month - 1 + desplazamiento
    anio, mes = divmod(meses, 12)
    return datetime(anio, mes + 1, 1, tzinfo=local.tzinfo)


def corte_retencion(ahora=None):
    """Conserva mes actual y anterior; noviembre elimina septiembre y anteriores."""
    return inicio_mes(ahora or timezone.now(), -1)


class AdministradorImagenes(models.Manager):
    def get_queryset(self):
        # Ninguna lista o consulta operativa carga los megabytes de la fotografía.
        return super().get_queryset().defer("contenido_base64")


class ModeloConImagenEnBaseDatos(models.Model):
    contenido_base64 = models.TextField(null=True, blank=True, editable=False)
    imagen_guardada_en = models.DateTimeField(null=True, blank=True, editable=False)
    imagen_eliminada_en = models.DateTimeField(null=True, blank=True, editable=False)
    archivo_original_eliminado_en = models.DateTimeField(null=True, blank=True, editable=False)

    objects = AdministradorImagenes()

    class Meta:
        abstract = True

    @property
    def imagen_expira_en(self):
        return inicio_mes(self.capturada_en, 2)

    @property
    def archivo_disponible(self):
        if self.imagen_eliminada_en is not None or timezone.now() >= self.imagen_expira_en:
            return False
        if self.imagen_guardada_en is not None:
            return True
        try:
            return bool(self.clave_almacenamiento) and default_storage.exists(self.clave_almacenamiento)
        except (OSError, ValueError, SuspiciousFileOperation):
            return False


def preparar_imagen_base64(archivo, ahora):
    archivo.seek(0)
    contenido = archivo.read()
    return {
        "contenido_base64": base64.b64encode(contenido).decode("ascii"),
        "imagen_guardada_en": ahora,
        # Las nuevas imágenes nunca crean un original en filesystem.
        "archivo_original_eliminado_en": ahora,
    }


class ImagenEliminadaPorRetencion(APIException):
    status_code = 410
    default_detail = "La fotografía fue eliminada por la retención mensual. El registro de evidencia se conserva."
    default_code = "imagen_eliminada_por_retencion"


def responder_archivo_imagen(evidencia):
    # Se invoca después de verificar propiedad/permisos, incluso si la tarea va atrasada.
    if evidencia.imagen_eliminada_en is not None or timezone.now() >= evidencia.imagen_expira_en:
        raise ImagenEliminadaPorRetencion()
    if evidencia.imagen_guardada_en is not None:
        try:
            codificado = evidencia.contenido_base64
            if not codificado or len(codificado) != 4 * ((evidencia.tamano_bytes + 2) // 3):
                raise ValueError()
            contenido = base64.b64decode(codificado, validate=True)
            if len(contenido) != evidencia.tamano_bytes:
                raise ValueError()
        except (ValueError, binascii.Error):
            raise Http404("El contenido de la imagen no está disponible.") from None
        archivo = BytesIO(contenido)
    else:
        # Compatibilidad temporal mientras se importan los originales anteriores.
        try:
            archivo = default_storage.open(evidencia.clave_almacenamiento, "rb")
        except (OSError, ValueError, SuspiciousFileOperation):
            raise Http404("El archivo anterior de la evidencia no está disponible.") from None
    respuesta = FileResponse(archivo, content_type=evidencia.tipo_contenido)
    respuesta["Content-Length"] = evidencia.tamano_bytes
    respuesta["Cache-Control"] = "private, no-store"
    respuesta["X-Content-Type-Options"] = "nosniff"
    return respuesta
