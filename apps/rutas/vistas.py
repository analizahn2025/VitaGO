"""Vistas HTTP de la ruta operativa del motorista."""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.nucleo.paginacion import PaginacionEstandar
from apps.rutas.selectores import obtener_mi_ruta
from apps.rutas.serializadores import SerializadorMiRuta, SerializadorCalcularRuta
from apps.rutas.ruta_vial import calcular_mi_ruta
from apps.rutas.selectores_historial import (
    listar_rutas_autorizadas,
    listar_versiones_autorizadas,
    obtener_version_autorizada,
)
from apps.rutas.serializadores_historial import (
    SerializadorFiltrosRutas,
    SerializadorRutaHistorica,
    SerializadorVersionRuta,
    SerializadorVersionRutaDetalle,
)


class VistaMiRuta(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        ruta = obtener_mi_ruta(request.user)
        return Response(SerializadorMiRuta(ruta).data)


class VistaRutasHistoricas(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        filtros = SerializadorFiltrosRutas(data=request.query_params)
        filtros.is_valid(raise_exception=True)
        consulta = listar_rutas_autorizadas(request.user, filtros.validated_data)
        paginacion = PaginacionEstandar()
        pagina = paginacion.paginate_queryset(consulta, request, view=self)
        return paginacion.get_paginated_response(
            SerializadorRutaHistorica(pagina, many=True).data
        )


class VistaCalcularMiRuta(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        entrada = SerializadorCalcularRuta(data=request.data)
        entrada.is_valid(raise_exception=True)
        return Response(calcular_mi_ruta(request.user, **entrada.validated_data))


class VistaVersionesRuta(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, ruta_id):
        consulta = listar_versiones_autorizadas(request.user, ruta_id)
        paginacion = PaginacionEstandar()
        pagina = paginacion.paginate_queryset(consulta, request, view=self)
        return paginacion.get_paginated_response(
            SerializadorVersionRuta(pagina, many=True).data
        )


class VistaDetalleVersionRuta(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, ruta_id, numero):
        version = obtener_version_autorizada(request.user, ruta_id, numero)
        return Response(SerializadorVersionRutaDetalle(version).data)
