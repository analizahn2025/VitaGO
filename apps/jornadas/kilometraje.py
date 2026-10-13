"""Kilometraje GPS de una jornada, congelado al finalizarla."""

from decimal import Decimal
from itertools import groupby

from django.db.models import Q

from apps.seguimiento.calidad import medir_puntos
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


def medir_jornada(jornada, finalizada_en):
    movimientos = list(MovimientoEnvioEspecial.objects.filter(
        jornada=jornada, repartidor=jornada.repartidor,
        estado=EstadoMovimientoEnvioEspecial.FINALIZADO, finalizada_en__lte=finalizada_en,
    ))
    especiales = _unir_intervalos((m.iniciada_en, m.finalizada_en) for m in movimientos)
    operativos = _unir_intervalos(_intervalos_de_asignaciones(jornada, finalizada_en) + especiales)
    normales = _restar_intervalos(operativos, especiales)
    resultado = medir_puntos([])
    resultado["especiales_sin_calidad"] = 0
    resultado["movimientos_pendientes"] = 0
    resultado["segundos_operativos"] = sum((fin - inicio).total_seconds() for inicio, fin in operativos)
    registros = RegistroUbicacion.objects.filter(
        jornada=jornada, repartidor=jornada.repartidor, es_operativo=True,
        movimiento_envio_especial__isnull=True,
        registrada_en__gte=jornada.iniciada_en, registrada_en__lte=finalizada_en,
    ).order_by("registrada_en", "id").values_list(
        "latitud", "longitud", "precision_metros", "velocidad_metros_segundo", "registrada_en",
    ).iterator(chunk_size=1000)
    indice = 0

    def tramo(punto):
        nonlocal indice
        while indice < len(normales) and punto[4] > normales[indice][1]:
            indice += 1
        if indice == len(normales) or punto[4] < normales[indice][0]:
            return -1
        return indice

    for grupo, puntos in groupby(registros, key=tramo):
        if grupo != -1:
            medicion = medir_puntos(puntos)
            for campo, valor in medicion.items():
                resultado[campo] += valor
    for movimiento in movimientos:
        resultado["kilometros"] += movimiento.kilometros_recorridos
        calidad = movimiento.calidad_kilometraje
        resultado["especiales_sin_calidad"] += int(not calidad)
        resultado["movimientos_pendientes"] += int(calidad.get("estado") == "PENDIENTE_SINCRONIZACION")
        for campo in (
            "puntos_considerados", "puntos_descartados", "puntos_sin_precision",
            "segmentos_validos", "huecos_detectados", "segundos_cubiertos",
        ):
            resultado[campo] += calidad.get(campo, 0)
    resultado["kilometros"] = resultado["kilometros"].quantize(Decimal("0.001"))
    return resultado


def calcular_kilometraje_operativo(jornada, finalizada_en):
    medicion = medir_jornada(jornada, finalizada_en)
    return medicion["kilometros"], bool(medicion["segmentos_validos"] or medicion["especiales_sin_calidad"])
