"""Posiciones utilizables para decisiones operativas, no puntos históricos."""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.jornadas.opciones import EstadoJornada
from apps.seguimiento.models import RegistroUbicacion


def posiciones_vigentes(ahora=None):
    ahora = ahora or timezone.now()
    return RegistroUbicacion.objects.filter(
        jornada__estado=EstadoJornada.ACTIVA,
        registrada_en__gte=ahora - timedelta(seconds=settings.ANTIGUEDAD_GPS_ASIGNACION_SEGUNDOS),
        registrada_en__lte=ahora,
        precision_metros__isnull=False,
        precision_metros__lte=settings.PRECISION_GPS_ASIGNACION_METROS,
    ).order_by("-registrada_en", "-id")
