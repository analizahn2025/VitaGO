"""Local development settings."""

from .base import *  # noqa: F403
from .base import (
    CLAVE_FIRMA_JWT_LOCAL as CLAVE_FIRMA_JWT_LOCAL_BASE,
    CLAVE_HASH_TOKEN_REFRESCO_LOCAL as CLAVE_HASH_TOKEN_REFRESCO_LOCAL_BASE,
    env,
)

DEBUG = env.bool("DEPURACION", default=True)
SECRET_KEY = env.str(
    "CLAVE_SECRETA",
    default="clave-insegura-solo-para-desarrollo-local",
)
ALLOWED_HOSTS = env.list(
    "SERVIDORES_PERMITIDOS",
    default=["localhost", "127.0.0.1", "testserver"],
)

CLAVE_FIRMA_JWT_LOCAL = env.str(
    "CLAVE_FIRMA_JWT_LOCAL",
    default=CLAVE_FIRMA_JWT_LOCAL_BASE
    or (
        "clave-jwt-insegura-solo-para-desarrollo-local-"
        "cambiar-antes-de-desplegar"
    ),
)
CLAVE_HASH_TOKEN_REFRESCO_LOCAL = env.str(
    "CLAVE_HASH_TOKEN_REFRESCO_LOCAL",
    default=CLAVE_HASH_TOKEN_REFRESCO_LOCAL_BASE
    or (
        "clave-hash-insegura-solo-para-desarrollo-local-"
        "cambiar-antes-de-desplegar"
    ),
)

SIMPLE_JWT["SIGNING_KEY"] = CLAVE_FIRMA_JWT_LOCAL  # noqa: F405

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "consola": {
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "vitago.api": {
            "handlers": ["consola"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
