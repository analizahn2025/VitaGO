"""Distancia transitoria a geometría vigente; no llama ni copia código de Google.

Formato de polilínea verificado en la documentación oficial:
https://developers.google.com/maps/documentation/utilities/polylinealgorithm?utm_campaign=gmp_git_agentskills_v1
Las coordenadas del proveedor no se persisten fuera de su caché existente.
"""

import math


def decodificar_polilinea(texto):
    if not isinstance(texto, str) or not 1 <= len(texto) <= 200000:
        return []
    puntos, indice, latitud, longitud = [], 0, 0, 0
    try:
        while indice < len(texto):
            cambios = []
            for _ in range(2):
                valor = desplazamiento = 0
                while True:
                    numero = ord(texto[indice]) - 63
                    indice += 1
                    if not 0 <= numero <= 63 or desplazamiento > 30:
                        return []
                    valor |= (numero & 31) << desplazamiento
                    desplazamiento += 5
                    if numero < 32:
                        break
                cambios.append(-(valor // 2) - 1 if valor & 1 else valor // 2)
            latitud += cambios[0]
            longitud += cambios[1]
            punto = latitud / 100000, longitud / 100000
            if not -90 <= punto[0] <= 90 or not -180 <= punto[1] <= 180 or len(puntos) >= 20000:
                return []
            puntos.append(punto)
    except (IndexError, TypeError, OverflowError):
        return []
    return puntos


def distancia_a_polilinea_metros(latitud, longitud, puntos):
    """Proyección local de los segmentos, con manejo del antimeridiano."""
    if not puntos:
        return None
    radio = 6371000
    coseno = max(1e-8, math.cos(math.radians(float(latitud))))

    def proyectar(punto):
        delta = (punto[1] - float(longitud) + 180) % 360 - 180
        return radio * math.radians(delta) * coseno, radio * math.radians(punto[0] - float(latitud))

    anterior = proyectar(puntos[0])
    minima = math.hypot(*anterior)
    for punto in puntos[1:]:
        actual = proyectar(punto)
        dx, dy = actual[0] - anterior[0], actual[1] - anterior[1]
        norma = dx*dx + dy*dy
        t = max(0, min(1, -(anterior[0]*dx + anterior[1]*dy) / norma)) if norma else 0
        minima = min(minima, math.hypot(anterior[0] + t*dx, anterior[1] + t*dy))
        anterior = actual
    return minima
