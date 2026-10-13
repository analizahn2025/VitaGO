"""Pruebas aisladas: no usan las bases ni el storage de desarrollo."""

import tempfile

from .local import *  # noqa: F403

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
_almacenamiento_temporal = tempfile.TemporaryDirectory(prefix="vitago-pruebas-")
MEDIA_ROOT = _almacenamiento_temporal.name
MODO_APLICACION = "CORPORATIVO"
PROVEEDOR_AUTENTICACION = "LOCAL"
ALLOWED_HOSTS = ["testserver", "localhost"]
