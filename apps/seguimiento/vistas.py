from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_201_CREATED
from rest_framework.views import APIView
from django.conf import settings
from django.utils import timezone

from apps.seguimiento.selectores import obtener_configuracion_gps, obtener_seguimiento_solicitud
from apps.seguimiento.serializadores import (
    SerializadorLoteRegistrosUbicacion,
    SerializadorLlegadaDetectada,
    SerializadorRegistroUbicacion,
    SerializadorSeguimientoSolicitud,
    SerializadorConsultaMotoristasSeguimiento, SerializadorMotoristaSeguimiento,
)
from apps.seguimiento.servicios import registrar_ubicaciones
from apps.seguimiento.motoristas import construir_posiciones_motoristas, listar_motoristas_en_jornada
from apps.nucleo.paginacion import PaginacionEstandar


class VistaMotoristasEnJornada(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        entrada = SerializadorConsultaMotoristasSeguimiento(data=request.query_params.dict())
        entrada.is_valid(raise_exception=True)
        ahora = timezone.now()
        consulta = listar_motoristas_en_jornada(request.user, entrada.validated_data, ahora)
        paginacion = PaginacionEstandar()
        pagina = paginacion.paginate_queryset(consulta, request, view=self)
        datos = construir_posiciones_motoristas(pagina, ahora)
        respuesta = paginacion.get_paginated_response(SerializadorMotoristaSeguimiento(datos, many=True).data)
        respuesta.data.update({
            "hora_servidor": ahora.isoformat(),
            "intervalo_actualizacion_segundos": settings.INTERVALO_GPS_ENVIO_SEGUNDOS,
            "criterios_vigencia": {
                "antiguedad_maxima_segundos": settings.ANTIGUEDAD_GPS_ASIGNACION_SEGUNDOS,
                "precision_maxima_metros": settings.PRECISION_GPS_ASIGNACION_METROS,
            },
        })
        respuesta["Cache-Control"] = "no-store"
        return respuesta


class VistaRegistroUbicaciones(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        entrada = SerializadorLoteRegistrosUbicacion(data=request.data)
        entrada.is_valid(raise_exception=True)
        resultado = registrar_ubicaciones(request.user, entrada.validated_data)
        return Response(
            {
                "recibidos": resultado["recibidos"],
                "creados": resultado["creados"],
                "repetidos": resultado["repetidos"],
                "alertas_ruta": resultado.get("alertas_ruta", []),
                "llegadas_detectadas": SerializadorLlegadaDetectada(
                    resultado["llegadas_detectadas"], many=True,
                ).data,
                "registros": SerializadorRegistroUbicacion(
                    resultado["registros"],
                    many=True,
                ).data,
            },
            status=HTTP_201_CREATED,
        )


class VistaConfiguracionGPS(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        return Response(obtener_configuracion_gps(request.user))


class VistaSeguimientoSolicitud(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, solicitud_id):
        seguimiento = obtener_seguimiento_solicitud(request.user, solicitud_id)
        return Response(
            SerializadorSeguimientoSolicitud(seguimiento).data,
            status=HTTP_200_OK,
        )
