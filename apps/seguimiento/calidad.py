"""Medición GPS común; nunca sustituye un hueco de señal por una ruta supuesta."""

from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings

from apps.seguimiento.distancias import distancia_kilometros


def medir_puntos(puntos):
    """Recibe (latitud, longitud, precisión, velocidad, fecha) ordenados."""
    anterior = None
    kilometros = 0.0
    resultado = {
        "puntos_considerados": 0, "puntos_descartados": 0,
        "puntos_sin_precision": 0, "segmentos_validos": 0,
        "huecos_detectados": 0, "segundos_cubiertos": 0.0,
    }
    for latitud, longitud, precision, velocidad, fecha in puntos:
        if (
            (precision is not None and float(precision) > settings.PRECISION_GPS_MAXIMA_METROS)
            or (velocidad is not None and float(velocidad) > settings.VELOCIDAD_GPS_MAXIMA_METROS_SEGUNDO)
        ):
            resultado["puntos_descartados"] += 1
            anterior = None
            continue
        resultado["puntos_considerados"] += 1
        if precision is None:
            resultado["puntos_sin_precision"] += 1
        actual = (latitud, longitud, precision, fecha)
        if anterior is None:
            anterior = actual
            continue
        segundos = (fecha - anterior[3]).total_seconds()
        if segundos <= 0:
            resultado["puntos_descartados"] += 1
            resultado["puntos_considerados"] -= 1
            resultado["puntos_sin_precision"] -= int(precision is None)
            anterior = None
            continue
        if segundos > settings.INTERVALO_GPS_MAXIMO_SEGUNDOS:
            resultado["huecos_detectados"] += 1
            anterior = actual
            continue
        distancia = distancia_kilometros(anterior[0], anterior[1], latitud, longitud)
        if distancia * 1000 / segundos > settings.VELOCIDAD_GPS_MAXIMA_METROS_SEGUNDO:
            resultado["puntos_descartados"] += 1
            resultado["puntos_considerados"] -= 1
            resultado["puntos_sin_precision"] -= int(precision is None)
            anterior = None
            continue
        resultado["segmentos_validos"] += 1
        resultado["segundos_cubiertos"] += segundos
        umbral = settings.DESPLAZAMIENTO_GPS_MINIMO_METROS
        if velocidad is None or float(velocidad) <= 0.5:
            umbral = max(umbral, min(float(precision or 0), float(anterior[2] or 0)))
        if distancia * 1000 <= umbral:
            # Mantiene el ancla espacial para no sumar oscilaciones estando parado.
            anterior = (anterior[0], anterior[1], anterior[2], fecha)
        else:
            kilometros += distancia
            anterior = actual
    resultado["kilometros"] = Decimal(str(kilometros)).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP,
    )
    return resultado
