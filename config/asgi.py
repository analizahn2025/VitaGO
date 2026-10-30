"""ASGI config for VitaGo."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

application = get_asgi_application()

from apps.jornadas.recuperacion import recuperar_al_arrancar  # noqa: E402

recuperar_al_arrancar()

