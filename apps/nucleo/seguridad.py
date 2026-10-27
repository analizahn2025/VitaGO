"""Errores públicos mínimos e informes internos sin credenciales ni cuerpos."""

import re

from django.http import JsonResponse
from django.views.debug import ExceptionReporter, SafeExceptionReporterFilter


class FiltroInformeErroresSeguro(SafeExceptionReporterFilter):
    """Amplía la censura de Django a los secretos nombrados en español."""

    hidden_settings = re.compile(
        SafeExceptionReporterFilter.hidden_settings.pattern
        + r"|CLAVE|CONTRASE[ÑN]A|CREDENCIAL|SECRETO|FIRMA|URL_BASE_DATOS|CONEXION",
        re.IGNORECASE,
    )

    def is_active(self, request):
        # El desarrollo también puede recibir solicitudes desde una red local.
        return True

    def get_cleansed_multivaluedict(self, request, multivaluedict):
        censurado = multivaluedict.copy()
        for nombre in censurado:
            censurado[nombre] = self.cleansed_substitute
        return censurado

    def get_post_parameters(self, request):
        if request is None:
            return {}
        return self.get_cleansed_multivaluedict(request, request.POST)

    def get_traceback_frame_variables(self, request, tb_frame):
        # Un serializer/objeto con nombre inocuo también puede contener tokens.
        # Se conserva la pila y el código, nunca los valores de sus variables.
        return [(nombre, self.cleansed_substitute) for nombre in tb_frame.f_locals]


class InformeErroresSeguro(ExceptionReporter):
    """Nunca envía un informe técnico al cliente, incluso con DEBUG activo."""

    def get_traceback_html(self):
        if self.is_email:
            return super().get_traceback_html()
        return (
            "<!doctype html><html lang='es'><meta charset='utf-8'>"
            "<title>No se pudo procesar la solicitud</title>"
            "<h1>No se pudo procesar la solicitud.</h1></html>"
        )

    def get_traceback_text(self):
        if self.is_email:
            return super().get_traceback_text()
        return "No se pudo procesar la solicitud."


class MiddlewareErroresSegurosAPI:
    """Conserva validación/autenticación; sustituye errores técnicos por JSON."""

    mensajes = {
        400: "La solicitud no es válida.",
        404: "No se encontró el recurso solicitado.",
        500: "Ocurrió un error interno. Intenta nuevamente más tarde.",
    }

    def __init__(self, obtener_respuesta):
        self.obtener_respuesta = obtener_respuesta

    def __call__(self, solicitud):
        respuesta = self.obtener_respuesta(solicitud)
        estado = respuesta.status_code
        if not solicitud.path.startswith("/api/") or estado not in self.mensajes:
            return respuesta

        tipo = respuesta.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if estado != 500 and (tipo == "application/json" or tipo.endswith("+json")):
            return respuesta

        segura = JsonResponse({"detail": self.mensajes[estado]}, status=estado)
        # Mantener cabeceras de seguridad sin reutilizar metadatos del cuerpo.
        for nombre, valor in respuesta.items():
            if nombre.lower() not in {
                "content-type", "content-length", "content-encoding", "etag"
            }:
                segura[nombre] = valor
        segura.cookies = respuesta.cookies
        segura["Cache-Control"] = "no-store"
        return segura
