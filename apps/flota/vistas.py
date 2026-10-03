from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_201_CREATED
from rest_framework.views import APIView

from apps.flota.selectores import (
    listar_vehiculos_autorizados,
    obtener_vehiculo_autorizado,
)
from apps.flota.serializadores import (
    SerializadorConsultaVehiculos,
    SerializadorCreacionVehiculo,
    SerializadorVehiculo,
)
from apps.flota.servicios import crear_vehiculo
from apps.nucleo.paginacion import PaginacionEstandar


class VistaListaCreacionVehiculos(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        entrada = SerializadorConsultaVehiculos(data=request.query_params)
        entrada.is_valid(raise_exception=True)
        vehiculos = listar_vehiculos_autorizados(
            request.user, entrada.validated_data
        )
        paginacion = PaginacionEstandar()
        pagina = paginacion.paginate_queryset(vehiculos, request, view=self)
        return paginacion.get_paginated_response(
            SerializadorVehiculo(pagina, many=True).data
        )

    def post(self, request):
        entrada = SerializadorCreacionVehiculo(data=request.data)
        entrada.is_valid(raise_exception=True)
        vehiculo = crear_vehiculo(request.user, entrada.validated_data)
        return Response(
            SerializadorVehiculo(vehiculo).data,
            status=HTTP_201_CREATED,
        )


class VistaDetalleVehiculo(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, vehiculo_id):
        vehiculo = obtener_vehiculo_autorizado(request.user, vehiculo_id)
        return Response(SerializadorVehiculo(vehiculo).data, status=HTTP_200_OK)
