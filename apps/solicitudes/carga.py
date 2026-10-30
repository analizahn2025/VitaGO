"""Corrección administrativa auditada de tubos y frascos."""

from django.db import transaction
from django.http import Http404
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.repartidores.capacidad import obtener_carga_recipientes, sincronizar_capacidad_repartidor
from apps.repartidores.models import Repartidor
from apps.repartidores.limites import obtener_limites_repartidor
from apps.solicitudes.models import EventoSolicitud, Solicitud
from apps.solicitudes.opciones import ESTADOS_SOLICITUD_ACTIVOS, EstadoSolicitud, TipoEventoSolicitud
from apps.solicitudes.recipientes import TIPOS_RECIPIENTE, validar_cantidades_recipientes
from apps.usuarios.servicios import usuario_tiene_permiso


@transaction.atomic
def actualizar_carga_recipientes(usuario, identificador, datos):
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
        campos = [f"cantidad_{tipo}" for tipo in TIPOS_RECIPIENTE if f"cantidad_{tipo}" in datos]
        raise ValidationError({campo: "No se modifica la carga de solicitudes terminadas." for campo in campos or ["detail"]})
    anteriores = {f"cantidad_{tipo}": getattr(solicitud, f"cantidad_{tipo}") for tipo in TIPOS_RECIPIENTE}
    nuevas = {campo: datos.get(campo, valor) for campo, valor in anteriores.items()}
    validar_cantidades_recipientes(**nuevas)
    cambiadas = [campo for campo in nuevas if nuevas[campo] != anteriores[campo]]
    if solicitud.estado in (EstadoSolicitud.RECOLECTADA, EstadoSolicitud.EN_TRANSITO, EstadoSolicitud.EN_DESTINO):
        errores = {campo: "La cantidad declarada no puede cambiar después de recoger el envío." for campo in cambiadas if anteriores[campo] is not None}
        if errores:
            raise ValidationError(errores)
    if not cambiadas:
        return solicitud
    repartidor = None
    if solicitud.repartidor_asignado_id:
        repartidor = Repartidor.objects.select_for_update(of=("self",)).get(pk=solicitud.repartidor_asignado_id)
        limites = obtener_limites_repartidor(repartidor, bloquear=True)
        carga = obtener_carga_recipientes(repartidor)
        errores = {}
        for tipo in TIPOS_RECIPIENTE:
            campo = f"cantidad_{tipo}"
            if carga[f"{tipo}_comprometidos"] - (anteriores[campo] or 0) + nuevas[campo] > limites[f"limite_{tipo}"]:
                errores[campo] = f"La modificación supera el cupo de {tipo} del motorista."
        if errores:
            raise ValidationError(errores)
    for campo in cambiadas:
        setattr(solicitud, campo, nuevas[campo])
    solicitud.save(update_fields=(*cambiadas, "actualizado_en"))
    metadatos = {f"{campo}_{momento}": valores[campo] for campo in anteriores for momento, valores in (("anterior", anteriores), ("nueva", nuevas))}
    EventoSolicitud.objects.create(
        solicitud=solicitud, tipo=TipoEventoSolicitud.CARGA_ACTUALIZADA, realizado_por=usuario,
        repartidor=repartidor, metadatos={**metadatos, "motivo": motivo,
                                        "regularizacion_historica": any(anteriores[campo] is None for campo in cambiadas)},
    )
    if repartidor:
        sincronizar_capacidad_repartidor(repartidor, usuario, "Carga de tubos y frascos actualizada por administración.")
    from apps.solicitudes.servicios import programar_reintento_pendientes
    programar_reintento_pendientes(solicitud.empresa_id)
    return solicitud
