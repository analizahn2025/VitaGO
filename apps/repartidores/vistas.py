from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_201_CREATED
from rest_framework.views import APIView

from apps.nucleo.paginacion import PaginacionEstandar
from apps.repartidores.selectores import (
    listar_repartidores_autorizados,
    listar_repartidores_disponibles,
    obtener_repartidor_autorizado,
    obtener_repartidor_propio,
)
from apps.repartidores.serializadores import (
    SerializadorActualizacionOperacionRepartidor,
    SerializadorConsultaRepartidores,
    SerializadorCreacionRepartidor,
    SerializadorRepartidor,
)
from apps.repartidores.servicios import (
    actualizar_operacion_repartidor,
    crear_repartidor,
)


def _respuesta_paginada(request, vista, consulta):
    paginacion = PaginacionEstandar()
    pagina = paginacion.paginate_queryset(consulta, request, view=vista)
    return paginacion.get_paginated_response(
        SerializadorRepartidor(pagina, many=True).data
    )


class VistaListaCreacionRepartidores(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        entrada = SerializadorConsultaRepartidores(data=request.query_params.dict())
        entrada.is_valid(raise_exception=True)
        consulta = listar_repartidores_autorizados(
            request.user, entrada.validated_data
        )
        return _respuesta_paginada(request, self, consulta)

    def post(self, request):
        entrada = SerializadorCreacionRepartidor(data=request.data)
        entrada.is_valid(raise_exception=True)
        repartidor = crear_repartidor(request.user, entrada.validated_data)
        return Response(
            SerializadorRepartidor(repartidor).data,
            status=HTTP_201_CREATED,
        )


class VistaRepartidoresDisponibles(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        entrada = SerializadorConsultaRepartidores(data=request.query_params.dict())
        entrada.is_valid(raise_exception=True)
        consulta = listar_repartidores_disponibles(
            request.user, entrada.validated_data
        )
        return _respuesta_paginada(request, self, consulta)


class VistaMiPerfilRepartidor(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        repartidor = obtener_repartidor_propio(request.user)
        return Response(
            SerializadorRepartidor(repartidor).data,
            status=HTTP_200_OK,
        )


class VistaDetalleRepartidor(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, repartidor_id):
        repartidor = obtener_repartidor_autorizado(request.user, repartidor_id)
        return Response(
            SerializadorRepartidor(repartidor).data,
            status=HTTP_200_OK,
        )


class VistaOperacionRepartidor(APIView):
    permission_classes = (IsAuthenticated,)

    def patch(self, request, repartidor_id):
        entrada = SerializadorActualizacionOperacionRepartidor(data=request.data)
        entrada.is_valid(raise_exception=True)
        repartidor = actualizar_operacion_repartidor(
            request.user,
            repartidor_id,
            entrada.validated_data,
        )
        return Response(
            SerializadorRepartidor(repartidor).data,
            status=HTTP_200_OK,
        )
