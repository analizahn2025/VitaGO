from django.http import Http404
from rest_framework.exceptions import PermissionDenied

from apps.evidencias.models import EvidenciaSolicitud
from apps.solicitudes.selectores import obtener_solicitud_autorizada
from apps.usuarios.servicios import usuario_tiene_permiso


def _obtener_solicitud_con_permiso_evidencias(usuario, solicitud_id):
    solicitud = obtener_solicitud_autorizada(usuario, solicitud_id)
    if not usuario_tiene_permiso(
        usuario,
        "evidencia.ver",
        empresa=solicitud.empresa,
        sucursal=solicitud.sucursal,
    ):
        raise PermissionDenied(
            'No tiene el permiso requerido: "evidencia.ver".'
        )
    return solicitud


def listar_evidencias_autorizadas(usuario, solicitud_id):
    solicitud = _obtener_solicitud_con_permiso_evidencias(
        usuario,
        solicitud_id,
    )
    return EvidenciaSolicitud.objects.filter(solicitud=solicitud).select_related(
        "repartidor",
        "repartidor__usuario",
    )


def obtener_evidencia_autorizada(usuario, solicitud_id, evidencia_id):
    solicitud = _obtener_solicitud_con_permiso_evidencias(
        usuario,
        solicitud_id,
    )
    try:
        return EvidenciaSolicitud.objects.select_related(
            "solicitud",
            "repartidor",
        ).get(id=evidencia_id, solicitud=solicitud)
    except (EvidenciaSolicitud.DoesNotExist, ValueError) as error:
        raise Http404(
            "La evidencia no existe o no está dentro de su alcance."
        ) from error

