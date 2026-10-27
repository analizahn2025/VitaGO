"""Limpieza local Corporate con entorno aislado y registro propio."""

from copy import deepcopy

from .tarea_corporativa import *  # noqa: F403

# Reutiliza carga .env.corporativo, validación LOCAL/CORPORATIVO y rotación.
# Copiar evita modificar el registro de la tarea de cierre diario.
LOGGING = deepcopy(LOGGING)  # noqa: F405
LOGGING["handlers"]["archivo_contingencias"]["filename"] = str(
    directorio_registros_tarea / "limpieza_rutas_google_corporativo.log"  # noqa: F405
)
