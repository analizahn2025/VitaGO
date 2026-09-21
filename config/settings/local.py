"""Local development settings."""

from .base import *  # noqa: F403
from .base import env

DEBUG = env.bool("DEPURACION", default=True)
SECRET_KEY = env.str(
    "CLAVE_SECRETA",
    default="clave-insegura-solo-para-desarrollo-local",
)
ALLOWED_HOSTS = env.list(
    "SERVIDORES_PERMITIDOS",
    default=["localhost", "127.0.0.1", "testserver"],
)

CLAVE_FIRMA_JWT_EXTERNO = env.str(
    "CLAVE_FIRMA_JWT_EXTERNO",
    default=(
        "clave-jwt-insegura-solo-para-desarrollo-local-"
        "cambiar-antes-de-desplegar"
    ),
)
CLAVE_HASH_TOKEN_REFRESCO = env.str(
    "CLAVE_HASH_TOKEN_REFRESCO",
    default=(
        "clave-hash-insegura-solo-para-desarrollo-local-"
        "cambiar-antes-de-desplegar"
    ),
)

SIMPLE_JWT["SIGNING_KEY"] = CLAVE_FIRMA_JWT_EXTERNO  # noqa: F405
