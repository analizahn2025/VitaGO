from django.core.files.storage import default_storage
from django.http import FileResponse, Http404
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_201_CREATED
from rest_framework.views import APIView

from apps.evidencias.selectores import (
    listar_evidencias_autorizadas,
    obtener_evidencia_autorizada,
)
from apps.evidencias.serializadores import (
    SerializadorEvidenciaSolicitud,
    SerializadorRegistroEvidencia,
)
from apps.evidencias.servicios import registrar_evidencia
from apps.nucleo.paginacion import PaginacionEstandar


class VistaListaRegistroEvidencias(APIView):
    permission_classes = (IsAuthenticated,)
    parser_classes = (MultiPartParser, FormParser)

    def get(self, request, solicitud_id):
        evidencias = listar_evidencias_autorizadas(request.user, solicitud_id)
        paginacion = PaginacionEstandar()
        pagina = paginacion.paginate_queryset(evidencias, request, view=self)
        datos = SerializadorEvidenciaSolicitud(pagina, many=True).data
        return paginacion.get_paginated_response(datos)

    def post(self, request, solicitud_id):
        entrada = SerializadorRegistroEvidencia(data=request.data)
        entrada.is_valid(raise_exception=True)
        evidencia = registrar_evidencia(
            request.user,
            solicitud_id,
            entrada.validated_data,
        )
        return Response(
            SerializadorEvidenciaSolicitud(evidencia).data,
            status=HTTP_201_CREATED,
        )


class VistaArchivoEvidencia(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, solicitud_id, evidencia_id):
        evidencia = obtener_evidencia_autorizada(
            request.user,
            solicitud_id,
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

