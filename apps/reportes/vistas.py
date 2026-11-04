from django.http import HttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.negotiation import DefaultContentNegotiation
from rest_framework.renderers import JSONRenderer
from rest_framework.views import APIView

from apps.reportes.exportadores import exportar_excel, exportar_pdf
from apps.reportes.selectores import construir_reporte_motoristas, construir_reporte_servicios
from apps.reportes.serializadores import SerializadorConsultaReporteMotoristas, SerializadorConsultaReporteServicios


class NegociacionDescarga(DefaultContentNegotiation):
    def select_renderer(self, request, renderers, format_suffix=None):
        # El archivo lo decide formato; los errores conservan siempre JSON,
        # incluso cuando el cliente solicita Accept: application/pdf.
        return renderers[0], renderers[0].media_type


class VistaDescargaReporte(APIView):
    permission_classes = (IsAuthenticated,)
    renderer_classes = (JSONRenderer,)
    content_negotiation_class = NegociacionDescarga

    def get(self, request):
        entrada = self.serializador(data=request.query_params.dict())
        entrada.is_valid(raise_exception=True)
        datos = self.constructor(request.user, entrada.validated_data)
        formato = entrada.validated_data["formato"]
        contenido, tipo = (exportar_excel(datos) if formato == "xlsx" else exportar_pdf(datos))
        if datos["tipo"] == "motoristas":
            periodo = "mensual" if datos["periodo"] == "MENSUAL" else f'quincena-{datos["quincena"]}'
            nombre = f'vitago-motoristas-{periodo}-{datos["mes"]}.{formato}'
        else:
            nombre = f'vitago-servicios-{datos["fecha_desde"]}.{formato}'
        respuesta = HttpResponse(contenido, content_type=tipo)
        respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
        respuesta["Cache-Control"] = "no-store, private"
        respuesta["Pragma"] = "no-cache"
        respuesta["X-Content-Type-Options"] = "nosniff"
        return respuesta


class VistaDescargaReporteMotoristas(VistaDescargaReporte):
    serializador = SerializadorConsultaReporteMotoristas
    constructor = staticmethod(construir_reporte_motoristas)


class VistaDescargaReporteServicios(VistaDescargaReporte):
    serializador = SerializadorConsultaReporteServicios
    constructor = staticmethod(construir_reporte_servicios)
