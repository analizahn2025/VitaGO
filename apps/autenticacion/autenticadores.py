"""Estrategias JWT seleccionadas centralmente por modo de despliegue."""

import jwt
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from apps.autenticacion.models import SesionAutenticacion
from apps.usuarios.models import Usuario


def _extraer_token_portador(solicitud):
    encabezado = get_authorization_header(solicitud).split()
    if not encabezado:
        return None
    if len(encabezado) != 2 or encabezado[0].lower() != b"bearer":
        raise AuthenticationFailed(
            "El encabezado de autorización debe usar el esquema Bearer."
        )
    try:
        return encabezado[1].decode("ascii")
    except UnicodeDecodeError as exc:
        raise AuthenticationFailed("El token de autorización no es válido.") from exc


class AutenticacionCorporativaJWT(BaseAuthentication):
    def authenticate(self, request):
        token_codificado = _extraer_token_portador(request)
        if token_codificado is None:
            return None

        clave_publica = settings.CLAVE_PUBLICA_JWT_CORPORATIVO
        emisor = settings.EMISOR_JWT_CORPORATIVO
        audiencia = settings.AUDIENCIA_JWT_CORPORATIVO
        claim_identidad = settings.CLAIM_IDENTIDAD_JWT_CORPORATIVO
        if not all((clave_publica, emisor, audiencia, claim_identidad)):
            raise ImproperlyConfigured(
                "La validación JWT corporativa no está configurada completamente."
            )

        try:
            claims = jwt.decode(
                token_codificado,
                clave_publica,
                algorithms=[settings.ALGORITMO_JWT_CORPORATIVO],
                audience=audiencia,
                issuer=emisor,
                leeway=settings.SEGUNDOS_TOLERANCIA_RELOJ_JWT,
                options={
                    "require": ["exp", "iss", "aud", claim_identidad],
                    "enforce_minimum_key_length": True,
                },
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationFailed("El token corporativo no es válido.") from exc

        identificador = claims.get(claim_identidad)
        if not isinstance(identificador, (str, int)) or not str(
            identificador
        ).strip():
            raise AuthenticationFailed(
                "El token corporativo no contiene una identidad válida."
            )

        try:
            usuario = Usuario.objetos.get(
                identificador_autenticacion_externa=str(identificador)
            )
        except Usuario.DoesNotExist as exc:
            raise AuthenticationFailed(
                "El usuario corporativo no está registrado en VitaGo."
            ) from exc

        if not usuario.is_active:
            raise AuthenticationFailed("El usuario no está activo.")

        return usuario, claims

    def authenticate_header(self, request):
        return "Bearer"


class AutenticacionExternaJWT(BaseAuthentication):
    def authenticate(self, request):
        token_codificado = _extraer_token_portador(request)
        if token_codificado is None:
            return None

        try:
            token = AccessToken(token_codificado)
            identificador_sesion = token["sesion_id"]
            identificador_usuario = token["usuario_id"]
            familia = token["familia"]
        except (TokenError, KeyError, TypeError, ValueError) as exc:
            raise AuthenticationFailed("El token de acceso no es válido.") from exc

        try:
            sesion = SesionAutenticacion.objetos.select_related("usuario").get(
                id=identificador_sesion,
                revocado_en__isnull=True,
                expira_en__gt=timezone.now(),
            )
        except (SesionAutenticacion.DoesNotExist, ValueError) as exc:
            raise AuthenticationFailed(
                "La sesión fue revocada, expiró o no existe."
            ) from exc

        if (
            str(sesion.usuario_id) != str(identificador_usuario)
            or str(sesion.familia) != str(familia)
        ):
            raise AuthenticationFailed(
                "El token de acceso no corresponde a la sesión registrada."
            )
        if not sesion.usuario.is_active:
            raise AuthenticationFailed("El usuario no está activo.")

        return sesion.usuario, token

    def authenticate_header(self, request):
        return "Bearer"


class AutenticacionVitaGo(BaseAuthentication):
    """Selecciona una estrategia sin dispersar condicionales por la API."""

    def authenticate(self, request):
        if settings.MODO_APLICACION == "CORPORATIVO":
            return AutenticacionCorporativaJWT().authenticate(request)
        return AutenticacionExternaJWT().authenticate(request)

    def authenticate_header(self, request):
        return "Bearer"
