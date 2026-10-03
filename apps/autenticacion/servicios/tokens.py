"""Creación y validación criptográfica de tokens propios de VitaGo."""

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.autenticacion.excepciones import TokenRefrescoInvalido


@dataclass(frozen=True, slots=True)
class ParTokens:
    token_acceso: str
    token_refresco: str
    expira_token_acceso_en: datetime
    expira_token_refresco_en: datetime
    identificador_token_refresco: str


def _fecha_claim(valor):
    return datetime.fromtimestamp(int(valor), tz=UTC)


def _clave_hash_token_refresco():
    clave = settings.CLAVE_HASH_TOKEN_REFRESCO_LOCAL
    if len(clave.encode("utf-8")) < 32:
        raise ImproperlyConfigured(
            "CLAVE_HASH_TOKEN_REFRESCO_LOCAL debe tener al menos 32 bytes."
        )
    return clave.encode("utf-8")


def calcular_hash_token_refresco(token_refresco):
    """Calcula una huella irreversible sin persistir el token recibido."""
    return hmac.new(
        _clave_hash_token_refresco(),
        token_refresco.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def crear_par_tokens(usuario, identificador_sesion, familia):
    token_refresco = RefreshToken.for_user(usuario)
    token_refresco["sesion_id"] = str(identificador_sesion)
    token_refresco["familia"] = str(familia)

    token_acceso = token_refresco.access_token
    return ParTokens(
        token_acceso=str(token_acceso),
        token_refresco=str(token_refresco),
        expira_token_acceso_en=_fecha_claim(token_acceso["exp"]),
        expira_token_refresco_en=_fecha_claim(token_refresco["exp"]),
        identificador_token_refresco=str(token_refresco["jti"]),
    )


def validar_token_refresco(token_codificado):
    try:
        token = RefreshToken(token_codificado)
        for claim in ("jti", "usuario_id", "sesion_id", "familia", "exp"):
            if claim not in token:
                raise TokenRefrescoInvalido(
                    f'El token de refresco no contiene el claim "{claim}".'
                )
        return token
    except TokenRefrescoInvalido:
        raise
    except (TokenError, TypeError, ValueError) as exc:
        raise TokenRefrescoInvalido() from exc
