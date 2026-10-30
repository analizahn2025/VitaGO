"""Observabilidad liviana para las solicitudes de la API."""

import logging
import time

from django.conf import settings
from django.http import JsonResponse


registrador = logging.getLogger("vitago.api")


class MiddlewareRecuperacionCierre:
    """Recupera al despertar y antes de responder con estados operativos antiguos."""

    def __init__(self, obtener_respuesta):
        self.obtener_respuesta = obtener_respuesta

    def __call__(self, solicitud):
        if solicitud.path.startswith(("/api/", "/admin/")):
            from apps.jornadas.recuperacion import recuperar_cierres_operativos

            if not recuperar_cierres_operativos():
                respuesta = JsonResponse({
                    "detail": "El servidor está recuperando el cierre operativo. Intente nuevamente en unos segundos.",
                    "codigo": "CIERRE_OPERATIVO_PENDIENTE",
                }, status=503)
                respuesta["Retry-After"] = "5"
                respuesta["Cache-Control"] = "no-store"
                return respuesta
        return self.obtener_respuesta(solicitud)


class MiddlewareRendimientoAPI:
    """Mide el tiempo interno sin registrar datos sensibles."""

    def __init__(self, obtener_respuesta):
        self.obtener_respuesta = obtener_respuesta

    def __call__(self, solicitud):
        if not solicitud.path.startswith("/api/"):
            return self.obtener_respuesta(solicitud)

        inicio = time.perf_counter()
        respuesta = self.obtener_respuesta(solicitud)
        duracion_ms = (time.perf_counter() - inicio) * 1000

        metrica = f"aplicacion;dur={duracion_ms:.2f}"
        metrica_existente = respuesta.headers.get("Server-Timing")
        respuesta.headers["Server-Timing"] = (
            f"{metrica_existente}, {metrica}"
            if metrica_existente
            else metrica
        )

        argumentos = (
            solicitud.method,
            solicitud.path,
            respuesta.status_code,
            duracion_ms,
        )
        if duracion_ms >= settings.UMBRAL_API_LENTA_MS:
            registrador.warning("API %s %s %s %.2fms", *argumentos)
        elif settings.REGISTRAR_RENDIMIENTO_API:
            registrador.info("API %s %s %s %.2fms", *argumentos)

        return respuesta
