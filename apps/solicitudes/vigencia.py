"""Vigencia diaria de los servicios en ambos sistemas."""

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.jornadas.horario import corte_operativo


def limite_dia_operativo(instante, empresa=None):
    return corte_operativo(instante, empresa)


def exigir_vigencia_solicitud(solicitud, ahora=None):
    if (ahora or timezone.now()) >= limite_dia_operativo(solicitud.creado_en, solicitud.empresa):
        raise ValidationError({"solicitud": "El día operativo de esta solicitud terminó; corresponde su cierre automático."})
