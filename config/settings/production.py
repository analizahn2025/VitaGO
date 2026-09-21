"""Production settings shared by Corporate and External deployments."""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import env

DEBUG = False

if not SECRET_KEY:  # noqa: F405
    raise ImproperlyConfigured("CLAVE_SECRETA es obligatoria en producción.")

if not env.str("URL_BASE_DATOS", default=""):
    raise ImproperlyConfigured("URL_BASE_DATOS es obligatoria en producción.")

if not ALLOWED_HOSTS:  # noqa: F405
    raise ImproperlyConfigured(
        "SERVIDORES_PERMITIDOS es obligatorio en producción."
    )

if SEGUNDOS_TOLERANCIA_RELOJ_JWT < 0:  # noqa: F405
    raise ImproperlyConfigured(
        "SEGUNDOS_TOLERANCIA_RELOJ_JWT no puede ser negativo."
    )

if MODO_APLICACION == "CORPORATIVO":  # noqa: F405
    if ALGORITMO_JWT_CORPORATIVO not in {"RS256", "RS384", "RS512"}:  # noqa: F405
        raise ImproperlyConfigured(
            "ALGORITMO_JWT_CORPORATIVO debe ser RS256, RS384 o RS512."
        )
    if not CLAVE_PUBLICA_JWT_CORPORATIVO:  # noqa: F405
        raise ImproperlyConfigured(
            "CLAVE_PUBLICA_JWT_CORPORATIVO es obligatoria en modo corporativo."
        )
    if not EMISOR_JWT_CORPORATIVO:  # noqa: F405
        raise ImproperlyConfigured(
            "EMISOR_JWT_CORPORATIVO es obligatorio en modo corporativo."
        )
    if not AUDIENCIA_JWT_CORPORATIVO:  # noqa: F405
        raise ImproperlyConfigured(
            "AUDIENCIA_JWT_CORPORATIVO es obligatoria en modo corporativo."
        )
elif MODO_APLICACION == "EXTERNO":  # noqa: F405
    if ALGORITMO_JWT_EXTERNO not in {"HS256", "HS384", "HS512"}:  # noqa: F405
        raise ImproperlyConfigured(
            "ALGORITMO_JWT_EXTERNO debe ser HS256, HS384 o HS512."
        )
    bytes_minimos_firma = {"HS256": 32, "HS384": 48, "HS512": 64}[
        ALGORITMO_JWT_EXTERNO  # noqa: F405
    ]
    if (  # noqa: F405
        len(CLAVE_FIRMA_JWT_EXTERNO.encode("utf-8"))
        < bytes_minimos_firma
    ):
        raise ImproperlyConfigured(
            "CLAVE_FIRMA_JWT_EXTERNO no alcanza la longitud mínima "
            "del algoritmo configurado."
        )
    if CLAVE_FIRMA_JWT_EXTERNO == SECRET_KEY:  # noqa: F405
        raise ImproperlyConfigured(
            "CLAVE_FIRMA_JWT_EXTERNO debe ser diferente de CLAVE_SECRETA."
        )
    if len(CLAVE_HASH_TOKEN_REFRESCO.encode("utf-8")) < 32:  # noqa: F405
        raise ImproperlyConfigured(
            "CLAVE_HASH_TOKEN_REFRESCO debe tener al menos 32 bytes."
        )
    if CLAVE_HASH_TOKEN_REFRESCO in {SECRET_KEY, CLAVE_FIRMA_JWT_EXTERNO}:  # noqa: F405
        raise ImproperlyConfigured(
            "CLAVE_HASH_TOKEN_REFRESCO debe ser un secreto independiente."
        )
    if MINUTOS_TOKEN_ACCESO <= 0:  # noqa: F405
        raise ImproperlyConfigured(
            "MINUTOS_TOKEN_ACCESO debe ser mayor que cero."
        )
    if DIAS_TOKEN_REFRESCO <= 0:  # noqa: F405
        raise ImproperlyConfigured(
            "DIAS_TOKEN_REFRESCO debe ser mayor que cero."
        )

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_SSL_REDIRECT = env.bool("REDIRECCION_SSL", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
