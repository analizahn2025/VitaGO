"""Producción en contenedor con paths escribibles y proxy explícito."""

from pathlib import Path

from .production import *  # noqa: F403
from .base import env

STATIC_ROOT = Path(env.str("RAIZ_ESTATICOS", default=str(BASE_DIR / "staticfiles")))  # noqa: F405
DATABASES["default"].setdefault("OPTIONS", {}).setdefault("connect_timeout", 5)  # noqa: F405
# Solo la comprobación mínima interna se permite sin redirección TLS.
SECURE_REDIRECT_EXEMPT = [r"^api/v1/salud/disponibilidad/$"]
for servidor_interno in ("127.0.0.1", "localhost"):
    if servidor_interno not in ALLOWED_HOSTS:  # noqa: F405
        ALLOWED_HOSTS.append(servidor_interno)  # noqa: F405
if env.bool("CONFIAR_PROXY_HTTPS", default=False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = env.list("ORIGENES_CSRF_CONFIABLES", default=[])
