from django.http import Http404

from apps.notificaciones.models import NotificacionUsuario
from apps.notificaciones.vigencia import limites_dia_operativo, notificaciones_vigentes


def listar_notificaciones(usuario):
    return notificaciones_vigentes().filter(usuario=usuario).select_related(
        "solicitud"
    )


def contar_no_leidas(usuario):
    return notificaciones_vigentes().filter(
        usuario=usuario, leida_en__isnull=True
    ).count()


def obtener_notificacion_propia(usuario, identificador, *, bloquear=False):
    try:
        consulta = notificaciones_vigentes()
        if bloquear:
            consulta = consulta.select_for_update(of=("self",))
        notificacion = consulta.get(id=identificador, usuario=usuario)
    except (NotificacionUsuario.DoesNotExist, ValueError) as error:
        raise Http404("La notificación no existe o no pertenece al usuario.") from error
    if bloquear:
        # Puede haber cruzado medianoche mientras esperaba el bloqueo de fila.
        inicio, fin = limites_dia_operativo()
        if not inicio <= notificacion.creado_en < fin or notificacion.archivada_en is not None:
            raise Http404("La notificación ya no está vigente.")
    return notificacion
