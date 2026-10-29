"""Calendario operativo del servidor, compartido por Corporate y Network."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError


def zona_operativa(empresa=None):
    nombre = settings.TIME_ZONE
    if settings.MODO_APLICACION == "CORPORATIVO" and empresa is not None:
        nombre = empresa.pais.zona_horaria_predeterminada
    return ZoneInfo(nombre)


def periodo_operativo(instante, empresa=None):
    zona = zona_operativa(empresa)
    fecha = instante.astimezone(zona).date()
    return (
        fecha,
        datetime.combine(fecha, time.min, tzinfo=zona),
        datetime.combine(fecha, time(22), tzinfo=zona),
    )


def corte_operativo(instante, empresa=None):
    # Un registro antiguo iniciado después del nuevo corte nunca debe cerrarse
    # antes de su inicio. Las nuevas jornadas se rechazan después de las 22:00.
    return max(instante, periodo_operativo(instante, empresa)[2])


def corte_jornada(jornada):
    return jornada.cierre_programado_en or corte_operativo(
        jornada.iniciada_en, jornada.repartidor.empresa,
    )


def jornada_vigente(jornada, ahora=None):
    return jornada is not None and jornada.estado == "ACTIVA" and (
        jornada.iniciada_en <= (ahora or timezone.now()) < corte_jornada(jornada)
    )


def exigir_jornada_vigente(jornada, ahora=None):
    if not jornada_vigente(jornada, ahora):
        raise ValidationError({"jornada": "Se requiere una jornada vigente; el día operativo termina a las 22:00."})


def umbral_cierre(ahora, empresa=None):
    """Antes de las 22 solo días anteriores; desde las 22 también el actual."""
    _, inicio, corte = periodo_operativo(ahora, empresa)
    return inicio + timedelta(days=1) if ahora >= corte else inicio


def anotar_jornada_y_almuerzo(consulta):
    from django.db.models import Exists, OuterRef, Subquery
    from apps.jornadas.models import AlmuerzoJornada, JornadaRepartidor

    ahora = timezone.now()
    vigentes = JornadaRepartidor.objects.filter(
        repartidor_id=OuterRef("pk"), estado="ACTIVA", iniciada_en__lte=ahora,
        cierre_programado_en__gt=ahora,
    )
    almuerzos = AlmuerzoJornada.objects.filter(
        jornada__repartidor_id=OuterRef("pk"), jornada__estado="ACTIVA",
        jornada__cierre_programado_en__gt=ahora, finalizada_en__isnull=True,
    ).order_by("-iniciada_en")
    return consulta.annotate(
        tiene_jornada_vigente=Exists(vigentes),
        en_almuerzo=Exists(almuerzos),
        almuerzo_iniciado_en=Subquery(almuerzos.values("iniciada_en")[:1]),
    )
