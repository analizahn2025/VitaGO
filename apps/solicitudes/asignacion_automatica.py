"""Orden de motoristas elegibles por cercanía GPS al origen."""

from math import asin, cos, radians, sin, sqrt

from django.conf import settings
from django.db.models import OuterRef, Subquery

from apps.repartidores.capacidad import (
    anotar_carga_repartidores,
    filtrar_repartidores_disponibles,
)
from apps.repartidores.models import Repartidor
from apps.seguimiento.vigencia import posiciones_vigentes


RADIO_TERRESTRE_KM = 6371.0088


def distancia_linea_recta_km(latitud_a, longitud_a, latitud_b, longitud_b):
    """Distancia geográfica de ordenación; no representa una ruta vial."""
    latitud_a, longitud_a, latitud_b, longitud_b = map(
        lambda valor: radians(float(valor)),
        (latitud_a, longitud_a, latitud_b, longitud_b),
    )
    diferencia_latitud = latitud_b - latitud_a
    diferencia_longitud = longitud_b - longitud_a
    termino = (
        sin(diferencia_latitud / 2) ** 2
        + cos(latitud_a) * cos(latitud_b) * sin(diferencia_longitud / 2) ** 2
    )
    return 2 * RADIO_TERRESTRE_KM * asin(min(1, sqrt(termino)))


def candidatos_ordenados(solicitud):
    """Ordena solo por GPS reciente y preciso; fallback explícito configurable."""
    if solicitud.cantidad_tubos is None or solicitud.cantidad_frascos is None:
        return []
    ultimo_gps = posiciones_vigentes().filter(repartidor_id=OuterRef("pk"))
    # Corporate: flota exclusiva de su empresa. Network: flota global, no
    # vinculada a ninguna empresa cliente; sigue exigiendo su rol operativo.
    empresa_id = None if settings.MODO_APLICACION == "EXTERNO" else solicitud.empresa_id
    consulta = filtrar_repartidores_disponibles(
        anotar_carga_repartidores(
            Repartidor.objects.filter(empresa_id=empresa_id)
        ), solicitud.cantidad_tubos, solicitud.cantidad_frascos
    ).annotate(
        ultima_latitud=Subquery(ultimo_gps.values("latitud")[:1]),
        ultima_longitud=Subquery(ultimo_gps.values("longitud")[:1]),
    )
    if settings.ASIGNACION_REQUIERE_GPS_VIGENTE:
        consulta = consulta.filter(ultima_latitud__isnull=False)
    candidatos = []
    for identificador, latitud, longitud in consulta.values_list(
        "id", "ultima_latitud", "ultima_longitud"
    ):
        distancia = None
        if latitud is not None and longitud is not None:
            distancia = distancia_linea_recta_km(
                solicitud.origen.latitud,
                solicitud.origen.longitud,
                latitud,
                longitud,
            )
        candidatos.append((identificador, distancia))
    return sorted(
        candidatos,
        key=lambda candidato: (
            candidato[1] is None,
            candidato[1] if candidato[1] is not None else 0,
            str(candidato[0]),
        ),
    )
