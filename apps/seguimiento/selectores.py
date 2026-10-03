"""Consultas contextuales y autorizadas para seguimiento operativo."""

from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.seguimiento.models import RegistroUbicacion
from apps.solicitudes.models import AsignacionSolicitud
from apps.solicitudes.opciones import EstadoAsignacionSolicitud, EstadoSolicitud
from apps.solicitudes.selectores import obtener_solicitud_autorizada
from apps.usuarios.servicios import usuario_tiene_permiso


ESTADOS_TERMINALES = {
    EstadoSolicitud.ENTREGADA, EstadoSolicitud.CANCELADA,
    EstadoSolicitud.RECOLECCION_FALLIDA, EstadoSolicitud.ENTREGA_FALLIDA,
}


def obtener_seguimiento_solicitud(usuario, solicitud_id):
    solicitud = obtener_solicitud_autorizada(usuario, solicitud_id)
    if not usuario_tiene_permiso(
        usuario, "solicitud.ver_seguimiento",
        empresa=solicitud.empresa, sucursal=solicitud.sucursal,
    ):
        raise PermissionDenied(
            'No tiene el permiso requerido: "solicitud.ver_seguimiento".'
        )

    disponible = bool(
        solicitud.repartidor_asignado_id and solicitud.estado not in ESTADOS_TERMINALES
    )
    ubicacion = None
    if disponible:
        asignacion = AsignacionSolicitud.objects.filter(
            solicitud=solicitud,
            repartidor_id=solicitud.repartidor_asignado_id,
            estado=EstadoAsignacionSolicitud.ACTIVA,
            aceptada_en__isnull=False,
        ).first()
        if asignacion:
            ubicacion = RegistroUbicacion.objects.filter(
                repartidor_id=solicitud.repartidor_asignado_id,
                es_operativo=True,
                registrada_en__gte=asignacion.aceptada_en,
                registrada_en__lte=timezone.now(),
            ).order_by("-registrada_en", "-id").first()

    return {
        "solicitud_id": solicitud.id,
        "estado": solicitud.estado,
        "seguimiento_disponible": disponible,
        "ubicacion": ubicacion,
    }
