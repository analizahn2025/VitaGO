"""Proceso local de mantenimiento: carga únicamente la configuración Corporate."""

import os

os.environ["ARCHIVO_ENTORNO_ADICIONAL"] = ".env.corporativo"

from .local import *  # noqa: E402,F403

from django.core.exceptions import ImproperlyConfigured

if ENTORNO != "LOCAL" or MODO_APLICACION != "CORPORATIVO":  # noqa: F405
    raise ImproperlyConfigured("Esta configuración solo admite la tarea Corporate local.")

directorio_registros_tarea = BASE_DIR / "logs"  # noqa: F405
directorio_registros_tarea.mkdir(exist_ok=True)
LOGGING["handlers"]["archivo_contingencias"] = {  # noqa: F405
    "class": "logging.handlers.RotatingFileHandler",
    "filename": str(directorio_registros_tarea / "contingencias_corporativo.log"),
    "maxBytes": 5_000_000,
    "backupCount": 3,
    "encoding": "utf-8",
}
LOGGING["loggers"]["vitago.api"]["handlers"] = ["archivo_contingencias"]  # noqa: F405
