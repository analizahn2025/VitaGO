"""Endpoints de empresas, sucursales y configuración compartida de cupos."""

from django.conf import settings
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_201_CREATED
from rest_framework.views import APIView

from apps.nucleo.paginacion import PaginacionEstandar
from apps.organizaciones.limites import configurar_limites_empresa, configurar_limites_red, exigir_modo_red
from apps.organizaciones.selectores import (
    listar_empresas_autorizadas,
    listar_sucursales_autorizadas,
    obtener_empresa_autorizada,
    obtener_sucursal_autorizada,
)
from apps.organizaciones.serializadores import (
    SerializadorCreacionSucursal,
    SerializadorConfiguracionLimitesMotoristas,
    SerializadorEmpresa,
    SerializadorLimitesMotoristas,
    SerializadorSucursal,
)
from apps.organizaciones.servicios import crear_sucursal
from apps.repartidores.limites import obtener_configuracion_red


def _entrada_limites(request):
    entrada = SerializadorConfiguracionLimitesMotoristas(data=request.data)
    entrada.is_valid(raise_exception=True)
    return entrada.validated_data


class VistaLimitesMotoristasEmpresa(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, empresa_id):
        empresa = obtener_empresa_autorizada(request.user, empresa_id)
        es_red = settings.MODO_APLICACION == "EXTERNO"
        configuracion = obtener_configuracion_red() if es_red else empresa
        return Response({"empresa_id": empresa.pk, "alcance": "RED" if es_red else "EMPRESA", **SerializadorLimitesMotoristas(configuracion).data})

    def patch(self, request, empresa_id):
        empresa = configurar_limites_empresa(request.user, empresa_id, _entrada_limites(request))
        return Response({"empresa_id": empresa.pk, "alcance": "EMPRESA", **SerializadorLimitesMotoristas(empresa).data})


class VistaLimitesMotoristasRed(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        exigir_modo_red()
        return Response({"alcance": "RED", **SerializadorLimitesMotoristas(obtener_configuracion_red()).data})

    def patch(self, request):
        configuracion = configurar_limites_red(request.user, _entrada_limites(request))
        return Response({"alcance": "RED", **SerializadorLimitesMotoristas(configuracion).data})


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
