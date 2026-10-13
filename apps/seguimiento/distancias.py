"""Cálculos geográficos compartidos; no representan distancia vial."""

from math import asin, cos, radians, sin, sqrt


def distancia_kilometros(latitud_a, longitud_a, latitud_b, longitud_b):
    """Distancia geodésica entre dos coordenadas, en kilómetros."""
    radio_tierra_km = 6371.0088
    latitud_a_rad = radians(float(latitud_a))
    latitud_b_rad = radians(float(latitud_b))
    delta_latitud = latitud_b_rad - latitud_a_rad
    delta_longitud = radians(float(longitud_b) - float(longitud_a))
    componente = (
        sin(delta_latitud / 2) ** 2
        + cos(latitud_a_rad)
        * cos(latitud_b_rad)
        * sin(delta_longitud / 2) ** 2
    )
    return 2 * radio_tierra_km * asin(min(1, sqrt(componente)))
