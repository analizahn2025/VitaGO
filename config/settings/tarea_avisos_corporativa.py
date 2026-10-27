"""Archivado Corporate en su base propia, sin modificar otras tareas."""

import os

os.environ["ARCHIVO_ENTORNO_ADICIONAL"] = ".env.corporativo"

from .tarea_avisos import *  # noqa: E402,F403

if MODO_APLICACION != "CORPORATIVO":  # noqa: F405
    raise ImproperlyConfigured("El archivado Corporate exige su entorno corporativo.")  # noqa: F405
