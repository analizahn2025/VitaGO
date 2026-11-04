"""Pruebas aisladas: no usan las bases ni el storage de desarrollo."""

import tempfile

from .local import *  # noqa: F403

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
_almacenamiento_temporal = tempfile.TemporaryDirectory(prefix="vitago-pruebas-")
MEDIA_ROOT = _almacenamiento_temporal.name
MODO_APLICACION = "CORPORATIVO"
PROVEEDOR_AUTENTICACION = "LOCAL"
# El calendario de los datos de prueba debe ser el mismo en Windows y Docker.
# Los casos de otras zonas lo sustituyen expresamente con override_settings.
TIME_ZONE = "America/Tegucigalpa"
ALLOWED_HOSTS = ["testserver", "localhost"]
# Las pruebas de recuperación lo habilitan explícitamente con sus propios datos.
HABILITAR_RECUPERACION_CIERRE = False
HABILITAR_MANTENIMIENTO_IMAGENES = False
