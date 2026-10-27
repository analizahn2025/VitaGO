"""Declaración de tubos y corrección administrativa auditada de la carga."""

from django.db import transaction
from django.http import Http404
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.repartidores.capacidad import obtener_carga_tubos, sincronizar_capacidad_repartidor
from apps.repartidores.models import Repartidor
from apps.solicitudes.models import EventoSolicitud, Solicitud
from apps.solicitudes.opciones import ESTADOS_SOLICITUD_ACTIVOS, EstadoSolicitud, TipoEventoSolicitud
from apps.usuarios.servicios import usuario_tiene_permiso


def validar_cantidad_tubos(valor):
    if isinstance(valor, bool) or not isinstance(valor, int) or not 1 <= valor <= 2147483647:
        raise ValidationError({"cantidad_tubos": "Debe indicar una cantidad entera de tubos mayor que cero."})
    return valor


@transaction.atomic
def actualizar_cantidad_tubos(usuario, identificador, datos):
    try:
        solicitud = Solicitud.objects.select_for_update(of=("self",), no_key=True).select_related("empresa", "sucursal").get(pk=identificador)
    except Solicitud.DoesNotExist as error:
        raise Http404("La solicitud no existe.") from error
    if not usuario_tiene_permiso(usuario, "solicitud.asignar", empresa=solicitud.empresa, sucursal=solicitud.sucursal):
        raise PermissionDenied('No tiene el permiso requerido: "solicitud.asignar".')
    motivo = (datos.get("motivo") or "").strip()
    if not motivo:
        raise ValidationError({"motivo": "Debe indicar el motivo de la corrección."})
    from apps.solicitudes.vigencia import exigir_vigencia_solicitud
    exigir_vigencia_solicitud(solicitud)
    if solicitud.estado not in (EstadoSolicitud.PENDIENTE, *ESTADOS_SOLICITUD_ACTIVOS):
        raise ValidationError({"cantidad_tubos": "No se modifica la carga de solicitudes terminadas."})
    anterior = solicitud.cantidad_tubos
    if anterior is not None and solicitud.estado in (EstadoSolicitud.RECOLECTADA, EstadoSolicitud.EN_TRANSITO, EstadoSolicitud.EN_DESTINO):
        raise ValidationError({"cantidad_tubos": "La cantidad declarada no puede cambiar después de recoger el envío."})
    cantidad = validar_cantidad_tubos(datos["cantidad_tubos"])
    if cantidad == anterior:
        return solicitud
    repartidor = None
    if solicitud.repartidor_asignado_id:
        repartidor = Repartidor.objects.select_for_update(of=("self",)).get(pk=solicitud.repartidor_asignado_id)
        carga = obtener_carga_tubos(repartidor)
        if anterior is not None and carga["tubos_comprometidos"] - anterior + cantidad > repartidor.limite_tubos:
            raise ValidationError({"cantidad_tubos": "La modificación supera el cupo de tubos del motorista."})
    solicitud.cantidad_tubos = cantidad
    solicitud.save(update_fields=("cantidad_tubos", "actualizado_en"))
    EventoSolicitud.objects.create(
        solicitud=solicitud, tipo=TipoEventoSolicitud.CARGA_ACTUALIZADA, realizado_por=usuario,
        repartidor=repartidor, metadatos={"cantidad_tubos_anterior": anterior, "cantidad_tubos_nueva": cantidad,
                                        "motivo": motivo, "regularizacion_historica": anterior is None},
    )
    if repartidor:
        sincronizar_capacidad_repartidor(repartidor, usuario, "Cantidad de tubos actualizada por administración.")
    from apps.solicitudes.servicios import programar_reintento_pendientes
    programar_reintento_pendientes(solicitud.empresa_id)
    return solicitud
