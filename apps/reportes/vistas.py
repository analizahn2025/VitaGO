from django.http import HttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.negotiation import DefaultContentNegotiation
from rest_framework.renderers import JSONRenderer
from rest_framework.views import APIView

from apps.reportes.exportadores import exportar_excel, exportar_pdf
from apps.reportes.selectores import construir_reporte_motoristas
from apps.reportes.serializadores import SerializadorConsultaReporteMotoristas


class NegociacionDescarga(DefaultContentNegotiation):
    def select_renderer(self, request, renderers, format_suffix=None):
        # El archivo lo decide formato; los errores conservan siempre JSON,
        # incluso cuando el cliente solicita Accept: application/pdf.
        return renderers[0], renderers[0].media_type


class VistaDescargaReporteMotoristas(APIView):
    permission_classes = (IsAuthenticated,)
    renderer_classes = (JSONRenderer,)
    content_negotiation_class = NegociacionDescarga

    def get(self, request):
        entrada = SerializadorConsultaReporteMotoristas(data=request.query_params.dict())
        entrada.is_valid(raise_exception=True)
        datos = construir_reporte_motoristas(request.user, entrada.validated_data)
        formato = entrada.validated_data["formato"]
        contenido, tipo = (exportar_excel(datos) if formato == "xlsx" else exportar_pdf(datos))
        nombre = f'vitago-motoristas-{datos["fecha_desde"]}-{datos["fecha_hasta"]}.{formato}'
        respuesta = HttpResponse(contenido, content_type=tipo)
        respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
        respuesta["Cache-Control"] = "no-store, private"
        respuesta["Pragma"] = "no-cache"
        respuesta["X-Content-Type-Options"] = "nosniff"
        return respuesta
