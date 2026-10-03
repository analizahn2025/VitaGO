"""Orden de motoristas elegibles por cercanía GPS al origen."""

from math import asin, cos, radians, sin, sqrt

from django.db.models import OuterRef, Subquery

from apps.repartidores.capacidad import (
    anotar_carga_repartidores,
    filtrar_repartidores_disponibles,
)
from apps.repartidores.models import Repartidor
from apps.seguimiento.models import RegistroUbicacion


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
    """Incluye al final motoristas elegibles que todavía no enviaron GPS."""
    ultimo_gps = RegistroUbicacion.objects.filter(
        repartidor_id=OuterRef("pk")
    ).order_by("-registrada_en", "-id")
    consulta = filtrar_repartidores_disponibles(
        anotar_carga_repartidores(
            Repartidor.objects.filter(empresa=solicitud.empresa)
        )
    ).annotate(
        ultima_latitud=Subquery(ultimo_gps.values("latitud")[:1]),
        ultima_longitud=Subquery(ultimo_gps.values("longitud")[:1]),
    )
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
