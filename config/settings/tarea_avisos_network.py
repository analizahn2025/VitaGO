"""Archivado Network en .env; nunca hereda el archivo Corporate."""

import os

os.environ.pop("ARCHIVO_ENTORNO_ADICIONAL", None)

from .tarea_avisos import *  # noqa: E402,F403

if MODO_APLICACION != "EXTERNO":  # noqa: F405
    raise ImproperlyConfigured("El archivado Network exige su entorno externo.")  # noqa: F405
