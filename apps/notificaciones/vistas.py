from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK
from rest_framework.views import APIView

from apps.notificaciones.selectores import (
    contar_no_leidas,
    listar_notificaciones,
    obtener_notificacion_propia,
)
from apps.notificaciones.serializadores import SerializadorNotificacion
from apps.notificaciones.servicios import marcar_notificacion_leida
from apps.nucleo.paginacion import PaginacionEstandar


class VistaListaNotificaciones(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        paginacion = PaginacionEstandar()
        pagina = paginacion.paginate_queryset(
            listar_notificaciones(request.user), request, view=self
        )
        return paginacion.get_paginated_response(
            SerializadorNotificacion(pagina, many=True).data
        )


class VistaConteoNoLeidas(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        return Response(
            {"conteo_no_leidas": contar_no_leidas(request.user)},
            status=HTTP_200_OK,
        )


class VistaMarcarNotificacionLeida(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, notificacion_id):
        notificacion = obtener_notificacion_propia(request.user, notificacion_id)
        notificacion = marcar_notificacion_leida(request.user, notificacion)
        return Response(SerializadorNotificacion(notificacion).data, status=HTTP_200_OK)
