from django.db import transaction
from django.utils import timezone

from apps.notificaciones.models import NotificacionUsuario
from apps.notificaciones.opciones import TipoNotificacion
from apps.solicitudes.opciones import PrioridadSolicitud


def crear_notificaciones_asignacion(solicitud, evento, repartidor, anterior=None):
    """Se invoca dentro de la transacción de asignación o reasignación."""
    if solicitud.prioridad == PrioridadSolicitud.PRIORITARIA:
        tipo = TipoNotificacion.SOLICITUD_PRIORITARIA
        titulo = "Servicio prioritario asignado"
    elif anterior is not None:
        tipo = TipoNotificacion.SOLICITUD_REASIGNADA
        titulo = "Servicio reasignado"
    else:
        tipo = TipoNotificacion.SOLICITUD_ASIGNADA
        titulo = "Nuevo servicio asignado"
    NotificacionUsuario.objects.create(
        usuario=repartidor.usuario,
        solicitud=solicitud,
        evento=evento,
        tipo=tipo,
        titulo=titulo,
        mensaje=f"Tienes asignada la solicitud {solicitud.numero}.",
    )
    if anterior is not None:
        NotificacionUsuario.objects.create(
            usuario=anterior.usuario,
            solicitud=solicitud,
            evento=evento,
            tipo=TipoNotificacion.SOLICITUD_RETIRADA,
            titulo="Servicio retirado de tu ruta",
            mensaje=f"La solicitud {solicitud.numero} fue reasignada.",
        )


@transaction.atomic
def marcar_notificacion_leida(usuario, notificacion):
    propia = NotificacionUsuario.objects.select_for_update().get(
        pk=notificacion.pk, usuario=usuario
    )
    if propia.leida_en is None:
        propia.leida_en = timezone.now()
        propia.save(update_fields=("leida_en", "actualizado_en"))
    return propia
