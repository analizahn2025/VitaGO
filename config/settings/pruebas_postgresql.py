"""PostgreSQL exclusivo del Compose de pruebas; rechaza destinos operativos."""

from django.core.exceptions import ImproperlyConfigured

from .pruebas import *  # noqa: F403
from .base import env

base_pruebas = env.db_url("URL_BASE_DATOS_PRUEBAS", default="")
if (base_pruebas.get("ENGINE") != "django.db.backends.postgresql"
        or base_pruebas.get("HOST") != "bd_pruebas"
        or base_pruebas.get("NAME") != "vitago_pruebas_docker"):
    raise ImproperlyConfigured("Las pruebas PostgreSQL requieren bd_pruebas/vitago_pruebas_docker aislada.")
base_pruebas["TEST"] = {"NAME": "test_vitago_docker"}
base_pruebas.setdefault("OPTIONS", {})["connect_timeout"] = 5
DATABASES = {"default": base_pruebas}
