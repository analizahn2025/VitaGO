"""Kilometraje GPS de una jornada, congelado al finalizarla."""

from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db.models import Q

from apps.seguimiento.distancias import distancia_kilometros
from apps.seguimiento.models import RegistroUbicacion
from apps.solicitudes.models import AsignacionSolicitud, MovimientoEnvioEspecial
from apps.solicitudes.opciones import EstadoMovimientoEnvioEspecial


def _unir_intervalos(intervalos):
    unidos = []
    for inicio, fin in sorted(intervalos):
        if inicio >= fin:
            continue
        if unidos and inicio <= unidos[-1][1]:
            unidos[-1] = (unidos[-1][0], max(unidos[-1][1], fin))
        else:
            unidos.append((inicio, fin))
    return unidos


def _intervalos_de_asignaciones(jornada, finalizada_en):
    asignaciones = (
        AsignacionSolicitud.objects.filter(
            repartidor=jornada.repartidor,
            aceptada_en__isnull=False,
            aceptada_en__lte=finalizada_en,
        )
        .filter(
            Q(finalizada_en__isnull=True)
            | Q(finalizada_en__gte=jornada.iniciada_en)
        )
        .values_list("aceptada_en", "finalizada_en")
    )
    return _unir_intervalos(
        (
            max(aceptada_en, jornada.iniciada_en),
            min(fin or finalizada_en, finalizada_en),
        )
        for aceptada_en, fin in asignaciones
    )


def _restar_intervalos(intervalos, excluidos):
    """Evita unir puntos anteriores y posteriores a un envío especial."""
    resultado = []
    for inicio, fin in intervalos:
        cursor = inicio
        for inicio_excluido, fin_excluido in excluidos:
            if fin_excluido <= cursor:
                continue
            if inicio_excluido >= fin:
                break
            if cursor < inicio_excluido:
                resultado.append((cursor, min(inicio_excluido, fin)))
            cursor = max(cursor, fin_excluido)
            if cursor >= fin:
                break
        if cursor < fin:
            resultado.append((cursor, fin))
    return resultado


def _calcular_kilometros_de_puntos(jornada, finalizada_en, intervalos):
    if not intervalos:
        return Decimal("0.000"), False

    precision_maxima = Decimal(str(settings.PRECISION_GPS_MAXIMA_METROS))
    velocidad_maxima = float(settings.VELOCIDAD_GPS_MAXIMA_METROS_SEGUNDO)
    registros = (
        RegistroUbicacion.objects.filter(
            jornada=jornada,
            repartidor=jornada.repartidor,
            es_operativo=True,
            movimiento_envio_especial__isnull=True,
            registrada_en__gte=jornada.iniciada_en,
            registrada_en__lte=finalizada_en,
        )
        .order_by("registrada_en", "id")
        .values_list(
            "latitud",
            "longitud",
            "precision_metros",
            "velocidad_metros_segundo",
            "registrada_en",
        )
        .iterator(chunk_size=1000)
    )
    indice_intervalo = 0
    anterior = None
    distancia_total = 0.0
    segmentos_validos = 0

    for latitud, longitud, precision, velocidad, registrada_en in registros:
        while (
            indice_intervalo < len(intervalos)
            and registrada_en > intervalos[indice_intervalo][1]
        ):
            indice_intervalo += 1
            anterior = None
        if indice_intervalo >= len(intervalos):
            break
        if registrada_en < intervalos[indice_intervalo][0]:
            anterior = None
            continue
        if (
            (precision is not None and precision > precision_maxima)
            or (velocidad is not None and float(velocidad) > velocidad_maxima)
        ):
            anterior = None
            continue

        if anterior is not None:
            segundos = (registrada_en - anterior[2]).total_seconds()
            if segundos <= 0:
                anterior = None
                continue
            distancia = distancia_kilometros(
                anterior[0], anterior[1], latitud, longitud
            )
            if distancia * 1000 / segundos > velocidad_maxima:
                anterior = None
                continue
            distancia_total += distancia
            segmentos_validos += 1
        anterior = (latitud, longitud, registrada_en)

    kilometros = Decimal(str(distancia_total)).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP
    )
    return kilometros, segmentos_validos > 0


def calcular_kilometraje_operativo(jornada, finalizada_en):
    """Suma tramos normales y especiales sin contar puntos personales dos veces."""
    movimientos = list(
        MovimientoEnvioEspecial.objects.filter(
            jornada=jornada,
            repartidor=jornada.repartidor,
            estado=EstadoMovimientoEnvioEspecial.FINALIZADO,
            finalizada_en__lte=finalizada_en,
        ).only("iniciada_en", "finalizada_en", "kilometros_recorridos")
    )
    intervalos_especiales = _unir_intervalos(
        (movimiento.iniciada_en, movimiento.finalizada_en)
        for movimiento in movimientos
    )
    intervalos_normales = _restar_intervalos(
        _intervalos_de_asignaciones(jornada, finalizada_en),
        intervalos_especiales,
    )
    kilometros_normales, tiene_segmentos = _calcular_kilometros_de_puntos(
        jornada, finalizada_en, intervalos_normales
    )
    kilometros_especiales = sum(
        (movimiento.kilometros_recorridos for movimiento in movimientos),
        Decimal("0.000"),
    )
    return (
        kilometros_normales + kilometros_especiales,
        tiene_segmentos or bool(movimientos),
    )
