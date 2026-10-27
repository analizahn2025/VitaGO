from django.db import transaction
from django.utils import timezone

from apps.notificaciones.models import NotificacionUsuario
from apps.notificaciones.opciones import TipoNotificacion
from apps.notificaciones.selectores import obtener_notificacion_propia
from apps.notificaciones.vigencia import limites_dia_operativo
from apps.solicitudes.opciones import PrioridadSolicitud


def crear_notificaciones_asignacion(solicitud, evento, repartidor, anterior=None):
    """Se invoca dentro de la transacción de asignación o reasignación."""
    if solicitud.prioridad == PrioridadSolicitud.PRIORITARIA:
        tipo = TipoNotificacion.SOLICITUD_PRIORITARIA
        titulo = "Servicio prioritario asignado"
    elif anterior is not None or evento.tipo == "REASIGNADA":
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
    propia = obtener_notificacion_propia(usuario, notificacion.pk, bloquear=True)
    if propia.leida_en is None:
        propia.leida_en = timezone.now()
        propia.save(update_fields=("leida_en", "actualizado_en"))
    return propia


def archivar_notificaciones_vencidas(*, simular=False):
    """Archiva todos los días pendientes sin modificar lectura ni otras tablas."""
    ahora = timezone.now()
    inicio, fin = limites_dia_operativo(ahora)
    vencidas = NotificacionUsuario.objects.filter(
        archivada_en__isnull=True, creado_en__lt=inicio,
    )
    cantidad = (
        vencidas.count() if simular else
        vencidas.update(archivada_en=ahora, actualizado_en=ahora)
    )
    return {
        "simulacion": simular,
        "avisos_vencidos": cantidad,
        "fecha_operativa": inicio.date().isoformat(),
        "zona_horaria_operativa": str(timezone.get_default_timezone()),
        "limite_exclusivo": inicio.isoformat(),
        "siguiente_corte_en": fin.isoformat(),
        "ejecutada_en": ahora.isoformat(),
    }
