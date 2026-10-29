from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_201_CREATED
from rest_framework.views import APIView

from apps.jornadas.selectores import (
    listar_jornadas_autorizadas,
    obtener_jornada_activa_propia,
    obtener_jornada_autorizada,
    estado_jornada_propia,
)
from apps.jornadas.serializadores import (
    SerializadorCierreJornada,
    SerializadorConsultaJornadas,
    SerializadorCoordenadasJornada,
    SerializadorJornada,
    SerializadorAccionAlmuerzo,
)
from apps.jornadas.servicios import cambiar_almuerzo, confirmar_sincronizacion_jornada, finalizar_jornada, iniciar_jornada
from apps.seguimiento.serializadores import SerializadorConfirmacionGPS, SerializadorRevisionKilometraje
from apps.nucleo.paginacion import PaginacionEstandar


class VistaListaJornadas(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        entrada = SerializadorConsultaJornadas(data=request.query_params)
        entrada.is_valid(raise_exception=True)
        jornadas = listar_jornadas_autorizadas(
            request.user,
            entrada.validated_data,
        )
        paginacion = PaginacionEstandar()
        pagina = paginacion.paginate_queryset(jornadas, request, view=self)
        datos = SerializadorJornada(pagina, many=True).data
        return paginacion.get_paginated_response(datos)


class VistaInicioJornada(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        entrada = SerializadorCoordenadasJornada(data=request.data)
        entrada.is_valid(raise_exception=True)
        jornada = iniciar_jornada(request.user, entrada.validated_data)
        return Response(
            SerializadorJornada(jornada).data,
            status=HTTP_201_CREATED,
        )


class VistaJornadaActiva(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        jornada, estado = estado_jornada_propia(request.user)
        return Response(
            {
                **estado,
                "jornada": (
                    SerializadorJornada(jornada).data if jornada else None
                )
            },
            status=HTTP_200_OK,
        )


class VistaInicioAlmuerzo(APIView):
    permission_classes = (IsAuthenticated,)
    iniciar = True

    def post(self, request, jornada_id):
        entrada = SerializadorAccionAlmuerzo(data=request.data)
        entrada.is_valid(raise_exception=True)
        jornada = cambiar_almuerzo(request.user, jornada_id, iniciar=self.iniciar)
        return Response(SerializadorJornada(jornada).data)


class VistaFinAlmuerzo(VistaInicioAlmuerzo):
    iniciar = False


class VistaDetalleJornada(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, jornada_id):
        jornada = obtener_jornada_autorizada(request.user, jornada_id)
        return Response(SerializadorJornada(jornada).data, status=HTTP_200_OK)


class VistaFinalizacionJornada(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, jornada_id):
        entrada = SerializadorCierreJornada(data=request.data)
        entrada.is_valid(raise_exception=True)
        jornada = finalizar_jornada(
            request.user,
            jornada_id,
            entrada.validated_data,
        )
        return Response(SerializadorJornada(jornada).data, status=HTTP_200_OK)


class VistaSincronizacionGPSJornada(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, jornada_id):
        entrada = SerializadorConfirmacionGPS(data=request.data)
        entrada.is_valid(raise_exception=True)
        jornada = confirmar_sincronizacion_jornada(request.user, jornada_id, entrada.validated_data)
        return Response(SerializadorJornada(jornada).data)


class VistaRevisionesKilometraje(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, jornada_id):
        from apps.seguimiento.models import RevisionKilometraje

        jornada = obtener_jornada_autorizada(request.user, jornada_id)
        consulta = RevisionKilometraje.objects.filter(jornada=jornada).order_by("-creado_en", "id")
        paginacion = PaginacionEstandar()
        pagina = paginacion.paginate_queryset(consulta, request, view=self)
        return paginacion.get_paginated_response(SerializadorRevisionKilometraje(pagina, many=True).data)

