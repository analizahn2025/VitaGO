"""Día de avisos definido por el servidor, independiente del reloj del cliente."""

from datetime import datetime, time, timedelta

from django.utils import timezone

from apps.notificaciones.models import NotificacionUsuario


def limites_dia_operativo(ahora=None):
    zona = timezone.get_default_timezone()
    fecha = (ahora or timezone.now()).astimezone(zona).date()
    return (
        datetime.combine(fecha, time.min, tzinfo=zona),
        datetime.combine(fecha + timedelta(days=1), time.min, tzinfo=zona),
    )


def notificaciones_vigentes(ahora=None):
    inicio, fin = limites_dia_operativo(ahora)
    return NotificacionUsuario.objects.filter(
        archivada_en__isnull=True, creado_en__gte=inicio, creado_en__lt=fin,
    )
