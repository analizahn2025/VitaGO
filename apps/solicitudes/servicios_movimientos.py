"""Inicio, asociación GPS y cierre de los envíos especiales."""

from decimal import Decimal, ROUND_HALF_UP
from math import asin, cos, radians, sin, sqrt

from django.conf import settings
from django.db.models import Q
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


def _distancia_kilometros(latitud_a, longitud_a, latitud_b, longitud_b):
    """Calcula distancia geodésica entre dos coordenadas."""
    radio_tierra_km = 6371.0088
    latitud_a_rad = radians(float(latitud_a))
    latitud_b_rad = radians(float(latitud_b))
    delta_latitud = latitud_b_rad - latitud_a_rad
    delta_longitud = radians(float(longitud_b) - float(longitud_a))
    componente = (
        sin(delta_latitud / 2) ** 2
        + cos(latitud_a_rad)
        * cos(latitud_b_rad)
        * sin(delta_longitud / 2) ** 2
    )
    return 2 * radio_tierra_km * asin(sqrt(componente))


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


def _calcular_recorrido(movimiento, registros, latitud_fin, longitud_fin, ahora):
    precision_maxima = Decimal(str(settings.PRECISION_GPS_MAXIMA_METROS))
    velocidad_maxima = float(settings.VELOCIDAD_GPS_MAXIMA_METROS_SEGUNDO)
    ultimo = (
        movimiento.latitud_inicio,
        movimiento.longitud_inicio,
        movimiento.iniciada_en,
    )
    distancia_total = 0.0
    considerados = 0
    descartados = 0

    for registro in registros:
        if (
            registro.precision_metros is not None
            and registro.precision_metros > precision_maxima
        ):
            descartados += 1
            continue
        if (
            registro.velocidad_metros_segundo is not None
            and float(registro.velocidad_metros_segundo) > velocidad_maxima
        ):
            descartados += 1
            continue
        segundos = (registro.registrada_en - ultimo[2]).total_seconds()
        if segundos <= 0:
            descartados += 1
            continue
        distancia = _distancia_kilometros(
            ultimo[0], ultimo[1], registro.latitud, registro.longitud
        )
        if distancia * 1000 / segundos > velocidad_maxima:
            descartados += 1
            continue
        distancia_total += distancia
        considerados += 1
        ultimo = (registro.latitud, registro.longitud, registro.registrada_en)

    segundos_finales = (ahora - ultimo[2]).total_seconds()
    if segundos_finales > 0:
        distancia_final = _distancia_kilometros(
            ultimo[0], ultimo[1], latitud_fin, longitud_fin
        )
        if distancia_final * 1000 / segundos_finales <= velocidad_maxima:
            distancia_total += distancia_final
    kilometros = Decimal(str(distancia_total)).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP
    )
    return kilometros, considerados, descartados


def cerrar_movimiento_especial(
    solicitud,
    repartidor,
    *,
    latitud,
    longitud,
    ahora,
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
    registros = list(
        registros_intervalo.filter(movimiento_envio_especial=movimiento).order_by(
            "registrada_en", "id"
        )
    )
    kilometros, considerados, descartados = _calcular_recorrido(
        movimiento,
        registros,
        latitud,
        longitud,
        ahora,
    )
    movimiento.estado = EstadoMovimientoEnvioEspecial.FINALIZADO
    movimiento.finalizada_en = ahora
    movimiento.latitud_fin = latitud
    movimiento.longitud_fin = longitud
    movimiento.kilometros_recorridos = kilometros
    movimiento.registros_considerados = considerados
    movimiento.registros_descartados = descartados
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
    return movimiento


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
