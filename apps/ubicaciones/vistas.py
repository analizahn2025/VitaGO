"""Endpoints HTTP de ubicaciones."""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_201_CREATED
from rest_framework.views import APIView

from apps.nucleo.paginacion import PaginacionEstandar
from apps.ubicaciones.selectores import (
    listar_tipos_ubicacion_autorizados,
    listar_ubicaciones_autorizadas,
    obtener_ubicacion_autorizada,
)
from apps.ubicaciones.serializadores import (
    SerializadorActualizacionAutorizacion,
    SerializadorCreacionUbicacion,
    SerializadorFiltroUbicaciones,
    SerializadorRelacionUbicacionEmpresa,
    SerializadorTipoUbicacion,
    SerializadorUbicacionAdministrada,
)
from apps.ubicaciones.servicios import (
    actualizar_autorizacion_ubicacion,
    registrar_ubicacion,
)


class VistaListaTiposUbicacion(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        tipos = listar_tipos_ubicacion_autorizados(request.user)
        datos = SerializadorTipoUbicacion(tipos, many=True).data
        return Response({"resultados": datos}, status=HTTP_200_OK)


class VistaListaCreacionUbicaciones(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        filtro = SerializadorFiltroUbicaciones(data=request.query_params)
        filtro.is_valid(raise_exception=True)
        _, relaciones = listar_ubicaciones_autorizadas(
            request.user,
            filtro.validated_data["empresa_id"],
        )
        paginacion = PaginacionEstandar()
        pagina = paginacion.paginate_queryset(relaciones, request, view=self)
        datos = SerializadorRelacionUbicacionEmpresa(pagina, many=True).data
        return paginacion.get_paginated_response(datos)

    def post(self, request):
        entrada = SerializadorCreacionUbicacion(data=request.data)
        entrada.is_valid(raise_exception=True)
        relacion = registrar_ubicacion(request.user, entrada.validated_data)
        return Response(
            SerializadorRelacionUbicacionEmpresa(relacion).data,
            status=HTTP_201_CREATED,
        )


class VistaDetalleUbicacion(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, ubicacion_id):
        ubicacion = obtener_ubicacion_autorizada(request.user, ubicacion_id)
        return Response(
            SerializadorUbicacionAdministrada(ubicacion).data,
            status=HTTP_200_OK,
        )


class VistaAutorizacionUbicacionEmpresa(APIView):
    permission_classes = (IsAuthenticated,)

    def patch(self, request, ubicacion_id, empresa_id):
        entrada = SerializadorActualizacionAutorizacion(data=request.data)
        entrada.is_valid(raise_exception=True)
        relacion = actualizar_autorizacion_ubicacion(
            request.user,
            ubicacion_id,
            empresa_id,
            entrada.validated_data,
        )
        return Response(
            SerializadorRelacionUbicacionEmpresa(relacion).data,
            status=HTTP_200_OK,
        )
