"""Ejecutor aislado: nunca usa el entrypoint de servidor ni su preparación."""

import os
import sys
from unittest.mock import patch


def main():
    if os.environ.get("DJANGO_SETTINGS_MODULE") != "config.settings.pruebas_postgresql":
        raise RuntimeError("El ejecutor requiere la configuración PostgreSQL aislada de pruebas.")
    import django
    django.setup()
    from django.core.management import call_command
    from scripts.docker.arranque import esperar_base_datos
    esperar_base_datos()
    with patch("apps.rutas.proveedor_google.urlopen", side_effect=AssertionError("No se permiten llamadas reales a Google en pruebas.")):
        call_command("test", *sys.argv[1:], interactive=False)


if __name__ == "__main__":
    main()
