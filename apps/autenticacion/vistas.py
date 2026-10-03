"""Endpoints HTTP del ciclo de autenticación."""

import ipaddress

from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed, NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_204_NO_CONTENT
from rest_framework.views import APIView

from apps.autenticacion.excepciones import ErrorAutenticacion
from apps.autenticacion.serializadores import (
    SerializadorInicioSesion,
    SerializadorRenovacionToken,
)
from apps.autenticacion.servicios.credenciales import autenticar_usuario_local
from apps.autenticacion.servicios.sesiones import (
    MetadatosSesion,
    cerrar_sesion,
    cerrar_todas_las_sesiones,
    crear_sesion,
    renovar_sesion,
)


def _exigir_proveedor_local():
    if settings.PROVEEDOR_AUTENTICACION != "LOCAL":
        raise NotFound(
            "Este endpoint no está disponible con el proveedor "
            "de autenticación actual."
        )


def _obtener_direccion_ip(solicitud):
    valor = solicitud.META.get("REMOTE_ADDR")
    if not valor:
        return None
    try:
        return str(ipaddress.ip_address(valor))
    except ValueError:
        return None


def _crear_metadatos(solicitud):
    agente_usuario = solicitud.META.get("HTTP_USER_AGENT") or None
    if agente_usuario:
        agente_usuario = agente_usuario[:2000]
    return MetadatosSesion(
        identificador_dispositivo=None,
        direccion_ip=_obtener_direccion_ip(solicitud),
        agente_usuario=agente_usuario,
    )


def _respuesta_tokens(resultado, incluir_usuario=False):
    datos = {
        "token_acceso": resultado.tokens.token_acceso,
        "token_refresco": resultado.tokens.token_refresco,
        "tipo_token": "Bearer",
        "expira_token_acceso_en": resultado.tokens.expira_token_acceso_en,
        "expira_token_refresco_en": resultado.tokens.expira_token_refresco_en,
        "sesion_id": resultado.sesion.id,
    }
    if incluir_usuario:
        usuario = resultado.sesion.usuario
        datos["usuario"] = {
            "id": usuario.id,
            "correo": usuario.correo,
            "nombres": usuario.nombres,
            "apellidos": usuario.apellidos,
        }
    return datos


def _elevar_error_autenticacion(error):
    raise AuthenticationFailed(detail=str(error), code=error.codigo) from error


class VistaAutenticacionPublica(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)

    def get_authenticate_header(self, request):
        return "Bearer"


class VistaInicioSesion(VistaAutenticacionPublica):
    def post(self, request):
        _exigir_proveedor_local()
        serializador = SerializadorInicioSesion(data=request.data)
        serializador.is_valid(raise_exception=True)

        try:
            usuario = autenticar_usuario_local(
                serializador.validated_data["correo"],
                serializador.validated_data["contrasena"],
            )
            resultado = crear_sesion(
                usuario,
                _crear_metadatos(request),
            )
        except ErrorAutenticacion as error:
            _elevar_error_autenticacion(error)

        return Response(
            _respuesta_tokens(resultado, incluir_usuario=True),
            status=HTTP_200_OK,
        )


class VistaRenovacionToken(VistaAutenticacionPublica):
    def post(self, request):
        _exigir_proveedor_local()
        serializador = SerializadorRenovacionToken(data=request.data)
        serializador.is_valid(raise_exception=True)

        try:
            resultado = renovar_sesion(
                serializador.validated_data["token_refresco"],
                _crear_metadatos(request),
            )
        except ErrorAutenticacion as error:
            _elevar_error_autenticacion(error)

        return Response(_respuesta_tokens(resultado), status=HTTP_200_OK)


class VistaCierreSesion(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        _exigir_proveedor_local()
        try:
            cerrar_sesion(request.user, request.auth["sesion_id"])
        except (ErrorAutenticacion, KeyError) as error:
            if isinstance(error, ErrorAutenticacion):
                _elevar_error_autenticacion(error)
            raise AuthenticationFailed("El token no identifica una sesión.") from error
        return Response(status=HTTP_204_NO_CONTENT)


class VistaCierreTotalSesiones(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        _exigir_proveedor_local()
        cerrar_todas_las_sesiones(request.user)
        return Response(status=HTTP_204_NO_CONTENT)
