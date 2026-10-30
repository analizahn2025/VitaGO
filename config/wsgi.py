"""WSGI config for VitaGo."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

application = get_wsgi_application()

from apps.jornadas.recuperacion import recuperar_al_arrancar  # noqa: E402

recuperar_al_arrancar()

