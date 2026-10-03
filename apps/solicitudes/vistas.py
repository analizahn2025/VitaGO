"""Endpoints HTTP del dominio de solicitudes."""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_201_CREATED
from rest_framework.views import APIView

from apps.nucleo.paginacion import PaginacionEstandar
from apps.solicitudes.opciones import EstadoSolicitud
from apps.solicitudes.selectores import (
    listar_solicitudes_autorizadas,
    listar_tipos_servicio_autorizados,
    obtener_opciones_creacion_solicitud,
    obtener_solicitud_autorizada,
    resumir_solicitudes_autorizadas,
)
from apps.solicitudes.serializadores import (
    SerializadorAsignacionManualSolicitud,
    SerializadorConsultaOpcionesCreacion,
    SerializadorConsultaResumenSolicitante,
    SerializadorConsultaSolicitudes,
    SerializadorCreacionSolicitud,
    SerializadorSolicitudDetalle,
    SerializadorSolicitudResumen,
    SerializadorTipoServicio,
    SerializadorTransicionSolicitud,
    SerializadorPuntoCreacionSolicitud,
)
from apps.solicitudes.servicios import (
    asignar_solicitud_manualmente,
    cambiar_estado_solicitud,
    crear_solicitud,
)


class VistaListaTiposServicio(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        tipos = listar_tipos_servicio_autorizados(request.user)
        return Response(
            {
                "resultados": SerializadorTipoServicio(
                    tipos,
                    many=True,
                ).data
            },
            status=HTTP_200_OK,
        )


class VistaOpcionesCreacionSolicitud(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        entrada = SerializadorConsultaOpcionesCreacion(
            data=request.query_params
        )
        entrada.is_valid(raise_exception=True)
        opciones = obtener_opciones_creacion_solicitud(
            request.user,
            entrada.validated_data,
        )
        return Response(
            {
                **opciones,
                "origenes": SerializadorPuntoCreacionSolicitud(
                    opciones["origenes"], many=True
                ).data,
                "destinos": SerializadorPuntoCreacionSolicitud(
                    opciones["destinos"], many=True
                ).data,
            },
            status=HTTP_200_OK,
        )


class VistaResumenSolicitante(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        entrada = SerializadorConsultaResumenSolicitante(
            data=request.query_params
        )
        entrada.is_valid(raise_exception=True)
        conteos, recientes = resumir_solicitudes_autorizadas(
            request.user,
            entrada.validated_data,
        )
        return Response(
            {
                **conteos,
                "recientes": SerializadorSolicitudResumen(
                    recientes,
                    many=True,
                ).data,
            },
            status=HTTP_200_OK,
        )


class VistaListaCreacionSolicitudes(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        entrada = SerializadorConsultaSolicitudes(data=request.query_params)
        entrada.is_valid(raise_exception=True)
        solicitudes = listar_solicitudes_autorizadas(
            request.user,
            entrada.validated_data,
        )
        paginacion = PaginacionEstandar()
        pagina = paginacion.paginate_queryset(solicitudes, request, view=self)
        datos = SerializadorSolicitudResumen(pagina, many=True).data
        return paginacion.get_paginated_response(datos)

    def post(self, request):
        entrada = SerializadorCreacionSolicitud(data=request.data)
        entrada.is_valid(raise_exception=True)
        solicitud = crear_solicitud(request.user, entrada.validated_data)
        if solicitud.estado == EstadoSolicitud.PENDIENTE:
            solicitud.refresh_from_db()
        return Response(
            SerializadorSolicitudDetalle(solicitud).data,
            status=HTTP_201_CREATED,
        )


class VistaDetalleSolicitud(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, solicitud_id):
        solicitud = obtener_solicitud_autorizada(
            request.user,
            solicitud_id,
        )
        return Response(
            SerializadorSolicitudDetalle(solicitud).data,
            status=HTTP_200_OK,
        )


class VistaAsignacionSolicitud(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, solicitud_id):
        entrada = SerializadorAsignacionManualSolicitud(data=request.data)
        entrada.is_valid(raise_exception=True)
        solicitud = asignar_solicitud_manualmente(
            request.user,
            solicitud_id,
            entrada.validated_data,
        )
        return Response(
            SerializadorSolicitudDetalle(solicitud).data,
            status=HTTP_201_CREATED,
        )


class VistaTransicionSolicitud(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, solicitud_id):
        entrada = SerializadorTransicionSolicitud(data=request.data)
        entrada.is_valid(raise_exception=True)
        solicitud = cambiar_estado_solicitud(
            request.user,
            solicitud_id,
            entrada.validated_data,
        )
        return Response(
            SerializadorSolicitudDetalle(solicitud).data,
            status=HTTP_200_OK,
        )
