"""Endpoints HTTP de consulta de organizaciones."""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_201_CREATED
from rest_framework.views import APIView

from apps.nucleo.paginacion import PaginacionEstandar
from apps.organizaciones.selectores import (
    listar_empresas_autorizadas,
    listar_sucursales_autorizadas,
    obtener_empresa_autorizada,
    obtener_sucursal_autorizada,
)
from apps.organizaciones.serializadores import (
    SerializadorCreacionSucursal,
    SerializadorEmpresa,
    SerializadorSucursal,
)
from apps.organizaciones.servicios import crear_sucursal


class VistaListaEmpresas(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        empresas = listar_empresas_autorizadas(request.user)
        paginacion = PaginacionEstandar()
        pagina = paginacion.paginate_queryset(empresas, request, view=self)
        datos = SerializadorEmpresa(pagina, many=True).data
        return paginacion.get_paginated_response(datos)


class VistaDetalleEmpresa(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, empresa_id):
        empresa = obtener_empresa_autorizada(request.user, empresa_id)
        return Response(
            SerializadorEmpresa(empresa).data,
            status=HTTP_200_OK,
        )


class VistaListaSucursalesEmpresa(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, empresa_id):
        _, sucursales = listar_sucursales_autorizadas(
            request.user,
            empresa_id,
        )
        paginacion = PaginacionEstandar()
        pagina = paginacion.paginate_queryset(sucursales, request, view=self)
        datos = SerializadorSucursal(pagina, many=True).data
        return paginacion.get_paginated_response(datos)

    def post(self, request, empresa_id):
        entrada = SerializadorCreacionSucursal(data=request.data)
        entrada.is_valid(raise_exception=True)
        sucursal = crear_sucursal(
            request.user,
            empresa_id,
            entrada.validated_data,
        )
        return Response(
            SerializadorSucursal(sucursal).data,
            status=HTTP_201_CREATED,
        )


class VistaDetalleSucursal(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, sucursal_id):
        sucursal = obtener_sucursal_autorizada(request.user, sucursal_id)
        return Response(
            SerializadorSucursal(sucursal).data,
            status=HTTP_200_OK,
        )
