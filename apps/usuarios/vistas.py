"""Endpoints HTTP de usuarios."""

from django.conf import settings
from django.http import Http404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_201_CREATED, HTTP_204_NO_CONTENT
from rest_framework.views import APIView

from apps.nucleo.paginacion import PaginacionEstandar
from apps.usuarios.selectores import (
    listar_asignaciones_roles_usuario_autorizadas,
    listar_usuarios_autorizados,
    obtener_perfil_usuario,
    obtener_usuario_autorizado,
)
from apps.usuarios.serializadores import (
    SerializadorActualizacionUsuario,
    SerializadorAsignacionRol,
    SerializadorAsignacionRolUsuario,
    SerializadorConsultaRolesAsignables,
    SerializadorCreacionUsuario,
    SerializadorPerfilUsuario,
    SerializadorRestablecimientoContrasena,
    SerializadorRolAsignable,
    SerializadorUsuarioAdministrado,
)
from apps.usuarios.servicios import (
    actualizar_usuario_administrado,
    asignar_rol_usuario,
    crear_usuario_administrado,
    listar_roles_asignables,
    restablecer_contrasena_usuario,
    revocar_rol_usuario,
)


class VistaMiPerfil(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        perfil = obtener_perfil_usuario(request.user)
        serializador = SerializadorPerfilUsuario(perfil)
        return Response(serializador.data, status=HTTP_200_OK)


class VistaListaCreacionUsuarios(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        usuarios = listar_usuarios_autorizados(request.user)
        paginacion = PaginacionEstandar()
        pagina = paginacion.paginate_queryset(usuarios, request, view=self)
        datos = SerializadorUsuarioAdministrado(pagina, many=True).data
        return paginacion.get_paginated_response(datos)

    def post(self, request):
        entrada = SerializadorCreacionUsuario(data=request.data)
        entrada.is_valid(raise_exception=True)
        usuario = crear_usuario_administrado(
            request.user,
            entrada.validated_data,
        )
        return Response(
            SerializadorUsuarioAdministrado(usuario).data,
            status=HTTP_201_CREATED,
        )


class VistaRolesAsignables(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        consulta = SerializadorConsultaRolesAsignables(data=request.query_params)
        consulta.is_valid(raise_exception=True)
        roles = listar_roles_asignables(request.user, **consulta.validated_data)
        return Response(
            {"resultados": SerializadorRolAsignable(roles, many=True).data},
            status=HTTP_200_OK,
        )


class VistaDetalleActualizacionUsuario(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, usuario_id):
        usuario = obtener_usuario_autorizado(request.user, usuario_id)
        return Response(
            SerializadorUsuarioAdministrado(usuario).data,
            status=HTTP_200_OK,
        )

    def patch(self, request, usuario_id):
        usuario = obtener_usuario_autorizado(
            request.user,
            usuario_id,
            codigo_permiso="usuario.administrar",
        )
        entrada = SerializadorActualizacionUsuario(data=request.data)
        entrada.is_valid(raise_exception=True)
        actualizado = actualizar_usuario_administrado(
            request.user,
            usuario,
            entrada.validated_data,
        )
        return Response(
            SerializadorUsuarioAdministrado(actualizado).data,
            status=HTTP_200_OK,
        )


class VistaRestablecimientoContrasena(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, usuario_id):
        if settings.PROVEEDOR_AUTENTICACION != "LOCAL":
            raise Http404(
                "El restablecimiento local no está disponible con este proveedor."
            )
        usuario = obtener_usuario_autorizado(
            request.user,
            usuario_id,
            codigo_permiso="usuario.administrar",
        )
        entrada = SerializadorRestablecimientoContrasena(
            data=request.data,
            context={"usuario_objetivo": usuario},
        )
        entrada.is_valid(raise_exception=True)
        restablecer_contrasena_usuario(
            request.user,
            usuario,
            entrada.validated_data["contrasena_temporal"],
        )
        return Response(status=HTTP_204_NO_CONTENT)


class VistaRolesUsuario(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, usuario_id):
        asignaciones = listar_asignaciones_roles_usuario_autorizadas(
            request.user,
            usuario_id,
        )
        return Response(
            {
                "resultados": SerializadorAsignacionRolUsuario(
                    asignaciones,
                    many=True,
                ).data
            },
            status=HTTP_200_OK,
        )

    def post(self, request, usuario_id):
        usuario = obtener_usuario_autorizado(
            request.user,
            usuario_id,
            codigo_permiso="usuario.administrar",
        )
        entrada = SerializadorAsignacionRol(data=request.data)
        entrada.is_valid(raise_exception=True)
        asignacion = asignar_rol_usuario(
            request.user,
            usuario,
            entrada.validated_data,
        )
        return Response(
            SerializadorAsignacionRolUsuario(asignacion).data,
            status=HTTP_201_CREATED,
        )


class VistaRevocacionRolUsuario(APIView):
    permission_classes = (IsAuthenticated,)

    def delete(self, request, usuario_id, asignacion_id):
        usuario = obtener_usuario_autorizado(
            request.user,
            usuario_id,
            codigo_permiso="usuario.administrar",
        )
        revocar_rol_usuario(
            request.user,
            usuario,
            asignacion_id,
        )
        return Response(status=HTTP_204_NO_CONTENT)
