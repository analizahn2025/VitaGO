"""Inicio, asociación GPS y cierre de los envíos especiales."""

from django.db import transaction
from django.db.models import Q
from django.http import Http404
from rest_framework.exceptions import ValidationError

from apps.jornadas.models import JornadaRepartidor
from apps.jornadas.opciones import EstadoJornada
from apps.seguimiento.models import RegistroUbicacion
from apps.solicitudes.models import AsignacionSolicitud, MovimientoEnvioEspecial
from apps.solicitudes.opciones import (
    EstadoAsignacionSolicitud,
    EstadoMovimientoEnvioEspecial,
    ModalidadSolicitud,
)


def iniciar_movimiento_especial(
    solicitud,
    repartidor,
    *,
    latitud,
    longitud,
    ahora,
):
    if solicitud.modalidad != ModalidadSolicitud.ESPECIAL:
        raise ValidationError(
            {"solicitud": "La solicitud no corresponde a un envío especial."}
        )
    if latitud is None or longitud is None:
        raise ValidationError(
            {"ubicacion": "Debe enviar la ubicación al iniciar el envío especial."}
        )
    try:
        jornada = JornadaRepartidor.objects.select_for_update().get(
            repartidor=repartidor,
            estado=EstadoJornada.ACTIVA,
        )
    except JornadaRepartidor.DoesNotExist as error:
        raise ValidationError(
            {"jornada": "El motorista debe tener una jornada activa."}
        ) from error
    if ahora < jornada.iniciada_en:
        raise ValidationError(
            {"jornada": "El movimiento no puede iniciar antes de la jornada."}
        )

    tiene_otra_asignacion = AsignacionSolicitud.objects.filter(
        repartidor=repartidor,
        estado=EstadoAsignacionSolicitud.ACTIVA,
    ).exclude(solicitud=solicitud).exists()
    if tiene_otra_asignacion:
        raise ValidationError(
            {
                "repartidor": (
                    "El envío especial requiere dedicación exclusiva y el "
                    "motorista posee otra asignación activa."
                )
            }
        )
    if MovimientoEnvioEspecial.objects.select_for_update().filter(
        repartidor=repartidor,
        estado=EstadoMovimientoEnvioEspecial.ACTIVO,
    ).exists():
        raise ValidationError(
            {"repartidor": "El motorista ya tiene un envío especial activo."}
        )

    return MovimientoEnvioEspecial.objects.create(
        solicitud=solicitud,
        repartidor=repartidor,
        jornada=jornada,
        estado=EstadoMovimientoEnvioEspecial.ACTIVO,
        iniciada_en=ahora,
        latitud_inicio=latitud,
        longitud_inicio=longitud,
    )


def cerrar_movimiento_especial(
    solicitud,
    repartidor,
    *,
    latitud,
    longitud,
    ahora,
    sesiones_gps=None,
):
    if latitud is None or longitud is None:
        raise ValidationError(
            {"ubicacion": "Debe enviar la ubicación al cerrar el envío especial."}
        )
    try:
        movimiento = MovimientoEnvioEspecial.objects.select_for_update().get(
            solicitud=solicitud,
            repartidor=repartidor,
            estado=EstadoMovimientoEnvioEspecial.ACTIVO,
        )
    except MovimientoEnvioEspecial.DoesNotExist as error:
        raise ValidationError(
            {"movimiento": "La solicitud no posee un envío especial activo."}
        ) from error
    if ahora <= movimiento.iniciada_en:
        raise ValidationError(
            {"movimiento": "El cierre debe ser posterior al inicio del movimiento."}
        )

    registros_intervalo = RegistroUbicacion.objects.filter(
        repartidor=repartidor,
        jornada=movimiento.jornada,
        registrada_en__gte=movimiento.iniciada_en,
        registrada_en__lte=ahora,
    )
    registros_intervalo.filter(
        Q(movimiento_envio_especial__isnull=True)
        | Q(movimiento_envio_especial=movimiento)
    ).update(movimiento_envio_especial=movimiento, es_operativo=True)
    movimiento.estado = EstadoMovimientoEnvioEspecial.FINALIZADO
    movimiento.finalizada_en = ahora
    movimiento.latitud_fin = latitud
    movimiento.longitud_fin = longitud
    movimiento.save(
        update_fields=(
            "estado",
            "finalizada_en",
            "latitud_fin",
            "longitud_fin",
            "kilometros_recorridos",
            "registros_considerados",
            "registros_descartados",
            "actualizado_en",
        )
    )
    from apps.seguimiento.sincronizacion import consolidar_movimiento

    return consolidar_movimiento(movimiento, sesiones_gps)


def obtener_movimientos_para_registros(repartidor, registros):
    if not registros:
        return []
    desde = min(registro["registrada_en"] for registro in registros)
    hasta = max(registro["registrada_en"] for registro in registros)
    return list(
        MovimientoEnvioEspecial.objects.filter(
            repartidor=repartidor,
            iniciada_en__lte=hasta,
        )
        .filter(Q(finalizada_en__isnull=True) | Q(finalizada_en__gte=desde))
        .only("id", "jornada_id", "iniciada_en", "finalizada_en")
    )


def movimiento_correspondiente(registrada_en, jornada_id, movimientos):
    for movimiento in movimientos:
        if movimiento.jornada_id != jornada_id:
            continue
        if movimiento.iniciada_en <= registrada_en and (
            movimiento.finalizada_en is None
            or registrada_en <= movimiento.finalizada_en
        ):
            return movimiento
    return None


@transaction.atomic
def confirmar_sincronizacion_movimiento(usuario, solicitud_id, datos):
    from apps.solicitudes.models import Solicitud
    from apps.solicitudes.servicios import _obtener_repartidor_operativo
    from apps.seguimiento.sincronizacion import consolidar_movimiento, normalizar_sesiones

    try:
        solicitud = Solicitud.objects.select_for_update().select_related("empresa", "sucursal").get(pk=solicitud_id)
    except Solicitud.DoesNotExist as error:
        raise Http404("La solicitud no existe.") from error
    repartidor = _obtener_repartidor_operativo(usuario, solicitud)
    try:
        movimiento = MovimientoEnvioEspecial.objects.select_for_update().get(
            solicitud=solicitud, repartidor=repartidor, estado=EstadoMovimientoEnvioEspecial.FINALIZADO,
        )
    except MovimientoEnvioEspecial.DoesNotExist as error:
        raise Http404("La solicitud no tiene un movimiento especial finalizado.") from error
    if not movimiento.calidad_kilometraje:
        raise ValidationError({"solicitud": "Los movimientos históricos no se recalculan."})
    if movimiento.calidad_kilometraje.get("sincronizacion_verificada"):
        if normalizar_sesiones(datos["sesiones_gps"]) != movimiento.calidad_kilometraje["sesiones_gps"]:
            raise ValidationError({"sesiones_gps": "El manifiesto del cierre consolidado es inmutable."})
        return movimiento
    jornada = JornadaRepartidor.objects.select_for_update().get(pk=movimiento.jornada_id)
    if jornada.calidad_kilometraje.get("sincronizacion_verificada"):
        raise ValidationError({"jornada": "La jornada ya fue consolidada."})
    consolidar_movimiento(movimiento, datos["sesiones_gps"], "CONFIRMACION_GPS")
    if jornada.finalizada_en and jornada.calidad_kilometraje:
        from apps.seguimiento.sincronizacion import consolidar_jornada

        consolidar_jornada(jornada, jornada.calidad_kilometraje.get("sesiones_gps"), "CONFIRMACION_GPS")
    return movimiento
