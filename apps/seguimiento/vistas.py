from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_201_CREATED
from rest_framework.views import APIView

from apps.seguimiento.selectores import obtener_seguimiento_solicitud
from apps.seguimiento.serializadores import (
    SerializadorLoteRegistrosUbicacion,
    SerializadorRegistroUbicacion,
    SerializadorSeguimientoSolicitud,
)
from apps.seguimiento.servicios import registrar_ubicaciones


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
                "registros": SerializadorRegistroUbicacion(
                    resultado["registros"],
                    many=True,
                ).data,
            },
            status=HTTP_201_CREATED,
        )


class VistaSeguimientoSolicitud(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, solicitud_id):
        seguimiento = obtener_seguimiento_solicitud(request.user, solicitud_id)
        return Response(
            SerializadorSeguimientoSolicitud(seguimiento).data,
            status=HTTP_200_OK,
        )
