"""Límites de día civil, exclusivamente para la operación corporativa."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError


def limite_dia_operativo(instante, empresa):
    zona = ZoneInfo(empresa.pais.zona_horaria_predeterminada)
    siguiente = instante.astimezone(zona).date() + timedelta(days=1)
    return datetime.combine(siguiente, time.min, tzinfo=zona)


def exigir_vigencia_solicitud(solicitud, ahora=None):
    if settings.MODO_APLICACION == "CORPORATIVO" and (
        ahora or timezone.now()
    ) >= limite_dia_operativo(solicitud.creado_en, solicitud.empresa):
        raise ValidationError({"solicitud": "El día operativo de esta solicitud terminó; corresponde su cierre automático."})
