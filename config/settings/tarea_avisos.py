"""Registro propio de avisos, sin importar ni ejecutar el cierre operativo."""

from copy import deepcopy

from django.core.exceptions import ImproperlyConfigured

from .local import *  # noqa: F403

if ENTORNO != "LOCAL" or MODO_APLICACION not in {"CORPORATIVO", "EXTERNO"}:  # noqa: F405
    raise ImproperlyConfigured("Esta configuración solo admite tareas locales de avisos.")

directorio_registros_avisos = BASE_DIR / "logs"  # noqa: F405
directorio_registros_avisos.mkdir(exist_ok=True)
LOGGING = deepcopy(LOGGING)  # noqa: F405
LOGGING["handlers"]["archivo_avisos"] = {
    "class": "logging.handlers.RotatingFileHandler",
    "filename": str(directorio_registros_avisos / f"avisos_{MODO_APLICACION.lower()}.log"),  # noqa: F405
    "maxBytes": 5_000_000,
    "backupCount": 3,
    "encoding": "utf-8",
}
LOGGING["loggers"]["vitago.api"]["handlers"] = ["archivo_avisos"]
