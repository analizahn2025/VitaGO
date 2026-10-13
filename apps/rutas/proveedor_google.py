"""Cliente REST mínimo de Routes API. Código propio basado en documentación verificada.

Documentación: https://developers.google.com/maps/documentation/routes/compute_route_directions?utm_campaign=gmp_git_agentskills_v1
No registra credenciales, direcciones, coordenadas ni cuerpos del proveedor.
"""

import json
import math
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.conf import settings


URL_COMPUTE_ROUTES = "https://routes.googleapis.com/directions/v2:computeRoutes"
MASCARA_CAMPOS = "routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline"
AVISO_MOTOCICLETA = (
    "Las rutas para motocicletas están en beta y pueden omitir aceras, senderos "
    "peatonales o ciclovías. Verifica que la vía sea apta y respeta las señales."
)


class SinRedirecciones(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Una redirección nunca debe reenviar la clave a otro destino.
        return None


urlopen = build_opener(SinRedirecciones()).open


class ErrorProveedorGoogle(Exception):
    def __init__(self, codigo, reintentable=False):
        self.codigo = codigo
        self.reintentable = reintentable
        super().__init__(codigo)


def _punto(latitud, longitud):
    try:
        latitud, longitud = float(latitud), float(longitud)
    except (TypeError, ValueError, OverflowError):
        raise ErrorProveedorGoogle("COORDENADAS_INVALIDAS") from None
    if not math.isfinite(latitud) or not math.isfinite(longitud) or not -90 <= latitud <= 90 or not -180 <= longitud <= 180:
        raise ErrorProveedorGoogle("COORDENADAS_INVALIDAS")
    return {"location": {"latLng": {"latitude": latitud, "longitude": longitud}}}


def calcular_ruta_google(origen, paradas):
    if not settings.HABILITAR_RUTAS_GOOGLE or not settings.CLAVE_API_GOOGLE_MAPS:
        raise ErrorProveedorGoogle("GOOGLE_NO_CONFIGURADO")
    if not 1 <= len(paradas) <= 10:
        raise ErrorProveedorGoogle("PARADAS_INVALIDAS")
    destinos = [_punto(p["latitud"], p["longitud"]) for p in paradas]
    cuerpo = {
        "origin": _punto(origen["latitud"], origen["longitud"]),
        "destination": destinos[-1], "intermediates": destinos[:-1],
        "travelMode": "TWO_WHEELER", "routingPreference": "TRAFFIC_AWARE",
        "computeAlternativeRoutes": False, "optimizeWaypointOrder": False,
        "languageCode": "es", "units": "METRIC",
    }
    solicitud = Request(URL_COMPUTE_ROUTES, data=json.dumps(cuerpo, allow_nan=False).encode("utf-8"), headers={
        "Content-Type": "application/json", "X-Goog-Api-Key": settings.CLAVE_API_GOOGLE_MAPS,
        "X-Goog-FieldMask": MASCARA_CAMPOS, "X-Goog-Maps-Solution-ID": "gmp_git_agentskills_v1",
    }, method="POST")
    try:
        with urlopen(solicitud, timeout=settings.RUTAS_GOOGLE_TIMEOUT_SEGUNDOS) as respuesta:
            contenido = respuesta.read(1048577)
            if len(contenido) > 1048576:
                raise ErrorProveedorGoogle("RESPUESTA_INVALIDA")
    except HTTPError as error:
        # No devolver el mensaje upstream: puede incluir parámetros o claves.
        error.close()
        if error.code == 429:
            raise ErrorProveedorGoogle("CUOTA_GOOGLE", True) from None
        if error.code in (401, 403):
            raise ErrorProveedorGoogle("CONFIGURACION_GOOGLE") from None
        raise ErrorProveedorGoogle("FALLA_GOOGLE", error.code >= 500) from None
    except (TimeoutError, socket.timeout, URLError, OSError):
        raise ErrorProveedorGoogle("CONEXION_GOOGLE", True) from None
    try:
        datos = json.loads(contenido)
        rutas = datos.get("routes", [])
        if not rutas:
            raise ErrorProveedorGoogle("SIN_RUTA")
        ruta = rutas[0]
        distancia = ruta["distanceMeters"]
        duracion_texto = ruta["duration"]
        polilinea = ruta["polyline"]["encodedPolyline"]
        if isinstance(distancia, bool) or not isinstance(distancia, int) or distancia < 0:
            raise ValueError()
        if not isinstance(duracion_texto, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,9})?s", duracion_texto):
            raise ValueError()
        duracion = float(duracion_texto[:-1])
        if not math.isfinite(duracion) or not isinstance(polilinea, str) or not 1 <= len(polilinea) <= 200000:
            raise ValueError()
        if any(not 63 <= ord(caracter) <= 126 for caracter in polilinea):
            raise ValueError()
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, UnicodeDecodeError):
        raise ErrorProveedorGoogle("RESPUESTA_INVALIDA") from None
    return {"distancia_estimada_metros": distancia, "duracion_estimada_segundos": duracion, "polilinea_codificada": polilinea}
