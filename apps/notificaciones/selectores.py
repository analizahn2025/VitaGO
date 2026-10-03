from django.http import Http404

from apps.notificaciones.models import NotificacionUsuario


def listar_notificaciones(usuario):
    return NotificacionUsuario.objects.filter(usuario=usuario).select_related(
        "solicitud"
    )


def contar_no_leidas(usuario):
    return NotificacionUsuario.objects.filter(
        usuario=usuario, leida_en__isnull=True
    ).count()


def obtener_notificacion_propia(usuario, identificador):
    try:
        return NotificacionUsuario.objects.get(id=identificador, usuario=usuario)
    except (NotificacionUsuario.DoesNotExist, ValueError) as error:
        raise Http404("La notificación no existe o no pertenece al usuario.") from error
