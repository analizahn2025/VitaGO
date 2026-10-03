from django.core.files.storage import default_storage
from django.http import FileResponse, Http404
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_201_CREATED
from rest_framework.views import APIView

from apps.incidencias.selectores import (
    listar_evidencias_incidencia_autorizadas,
    listar_incidencias_autorizadas,
    obtener_evidencia_incidencia_autorizada,
    obtener_incidencia_autorizada,
)
from apps.incidencias.serializadores import (
    SerializadorConsultaIncidencias,
    SerializadorCreacionIncidencia,
    SerializadorEvidenciaIncidencia,
    SerializadorIncidencia,
    SerializadorRegistroEvidenciaIncidencia,
    SerializadorRevisionIncidencia,
)
from apps.incidencias.servicios import (
    crear_incidencia,
    registrar_evidencia_incidencia,
    revisar_incidencia,
)
from apps.nucleo.paginacion import PaginacionEstandar


class VistaListaCreacionIncidencias(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        entrada = SerializadorConsultaIncidencias(data=request.query_params)
        entrada.is_valid(raise_exception=True)
        incidencias = listar_incidencias_autorizadas(
            request.user,
            entrada.validated_data,
        )
        paginacion = PaginacionEstandar()
        pagina = paginacion.paginate_queryset(incidencias, request, view=self)
        datos = SerializadorIncidencia(pagina, many=True).data
        return paginacion.get_paginated_response(datos)

    def post(self, request):
        entrada = SerializadorCreacionIncidencia(data=request.data)
        entrada.is_valid(raise_exception=True)
        incidencia = crear_incidencia(request.user, entrada.validated_data)
        return Response(
            SerializadorIncidencia(incidencia).data,
            status=HTTP_201_CREATED,
        )


class VistaDetalleIncidencia(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, incidencia_id):
        incidencia = obtener_incidencia_autorizada(
            request.user,
            incidencia_id,
        )
        return Response(
            SerializadorIncidencia(incidencia).data,
            status=HTTP_200_OK,
        )


class VistaRevisionIncidencia(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, incidencia_id):
        entrada = SerializadorRevisionIncidencia(data=request.data)
        entrada.is_valid(raise_exception=True)
        incidencia = revisar_incidencia(
            request.user,
            incidencia_id,
            entrada.validated_data,
        )
        return Response(
            SerializadorIncidencia(incidencia).data,
            status=HTTP_200_OK,
        )


class VistaListaRegistroEvidenciasIncidencia(APIView):
    permission_classes = (IsAuthenticated,)
    parser_classes = (MultiPartParser, FormParser)

    def get(self, request, incidencia_id):
        evidencias = listar_evidencias_incidencia_autorizadas(
            request.user,
            incidencia_id,
        )
        paginacion = PaginacionEstandar()
        pagina = paginacion.paginate_queryset(evidencias, request, view=self)
        datos = SerializadorEvidenciaIncidencia(pagina, many=True).data
        return paginacion.get_paginated_response(datos)

    def post(self, request, incidencia_id):
        entrada = SerializadorRegistroEvidenciaIncidencia(data=request.data)
        entrada.is_valid(raise_exception=True)
        evidencia = registrar_evidencia_incidencia(
            request.user,
            incidencia_id,
            entrada.validated_data,
        )
        return Response(
            SerializadorEvidenciaIncidencia(evidencia).data,
            status=HTTP_201_CREATED,
        )


class VistaArchivoEvidenciaIncidencia(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, incidencia_id, evidencia_id):
        evidencia = obtener_evidencia_incidencia_autorizada(
            request.user,
            incidencia_id,
            evidencia_id,
        )
        if not default_storage.exists(evidencia.clave_almacenamiento):
            raise Http404("El archivo de la evidencia no está disponible.")
        archivo = default_storage.open(evidencia.clave_almacenamiento, "rb")
        respuesta = FileResponse(
            archivo,
            content_type=evidencia.tipo_contenido,
        )
        respuesta["Content-Length"] = evidencia.tamano_bytes
        respuesta["Cache-Control"] = "private, no-store"
        respuesta["X-Content-Type-Options"] = "nosniff"
        return respuesta

