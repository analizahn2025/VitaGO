"""Consolidación verificable, revisiones y recepción de puntos tardíos."""

from django.conf import settings
from django.db.models import Count, Max
from django.utils import timezone

from apps.seguimiento.calidad import medir_puntos
from apps.seguimiento.models import RegistroUbicacion, RevisionKilometraje


def comprobar_sesiones(jornada, sesiones, hasta):
    if sesiones is None:
        return False, None
    registros = RegistroUbicacion.objects.filter(jornada=jornada, registrada_en__lte=hasta)
    if registros.filter(sesion_gps__isnull=True).exists():
        return False, None
    resumen = {
        str(item["sesion_gps"]): item
        for item in registros.values("sesion_gps").annotate(cantidad=Count("id"), ultima=Max("secuencia"))
    }
    previstas = {str(s["sesion_gps"]): int(s["ultima_secuencia"]) for s in sesiones}
    if set(resumen) - set(previstas):
        return False, None
    pendientes = 0
    for sesion, ultima in previstas.items():
        datos = resumen.get(sesion)
        if datos is None:
            pendientes += ultima
        elif datos["ultima"] > ultima:
            return False, None
        else:
            pendientes += ultima - datos["cantidad"]
    return pendientes == 0, pendientes


def normalizar_sesiones(sesiones):
    if sesiones is None:
        return None
    return sorted(
        ({"sesion_gps": str(s["sesion_gps"]), "ultima_secuencia": int(s["ultima_secuencia"])} for s in sesiones),
        key=lambda s: s["sesion_gps"],
    )


def _guardar_medicion(objeto, medicion, sesiones, hasta, motivo):
    es_movimiento = hasattr(objeto, "solicitud_id")
    jornada = objeto.jornada if es_movimiento else objeto
    verificada, pendientes = comprobar_sesiones(jornada, sesiones, hasta)
    verificada = verificada and not medicion.get("movimientos_pendientes", 0)
    segundos = medicion["segundos_operativos"]
    cobertura = min(100.0, 100 * medicion["segundos_cubiertos"] / segundos) if segundos else 0.0
    if sesiones is None:
        estado = "SIN_VERIFICAR"
    elif not verificada or medicion.get("movimientos_pendientes"):
        estado = "PENDIENTE_SINCRONIZACION"
    elif medicion.get("especiales_sin_calidad"):
        estado = "INCOMPLETO"
    elif not medicion["segmentos_validos"]:
        estado = "SIN_DATOS"
    elif cobertura < settings.COBERTURA_GPS_MINIMA_PORCENTAJE or medicion["puntos_sin_precision"]:
        estado = "INCOMPLETO"
    else:
        estado = "CONSOLIDADO"
    calidad = {
        campo: round(valor, 3) if isinstance(valor, float) else valor
        for campo, valor in medicion.items() if campo != "kilometros"
    }
    calidad.update(
        estado=estado, metodo="GPS_FILTRADO", sincronizacion_verificada=verificada,
        puntos_pendientes=pendientes, cobertura_porcentaje=round(cobertura, 2),
        sesiones_gps=normalizar_sesiones(sesiones),
    )
    previa = objeto.calidad_kilometraje
    comparable = {k: v for k, v in previa.items() if k not in ("revision", "actualizada_en")}
    campo_km = "kilometros_recorridos" if es_movimiento else "kilometros_operativos"
    if comparable == calidad and getattr(objeto, campo_km) == medicion["kilometros"]:
        return objeto
    calidad["revision"] = previa.get("revision", 0) + 1
    calidad["actualizada_en"] = timezone.now().isoformat()
    objeto.calidad_kilometraje = calidad
    setattr(objeto, campo_km, medicion["kilometros"])
    campos = [campo_km, "calidad_kilometraje", "actualizado_en"]
    if es_movimiento:
        objeto.registros_considerados = medicion["puntos_considerados"]
        objeto.registros_descartados = medicion["puntos_descartados"]
        campos += ["registros_considerados", "registros_descartados"]
    else:
        objeto.kilometraje_disponible = bool(medicion["segmentos_validos"] or medicion.get("especiales_sin_calidad"))
        objeto.minutos_operativos = int(segundos // 60)
        campos += ["kilometraje_disponible", "minutos_operativos"]
    objeto.save(update_fields=campos)
    RevisionKilometraje.objects.create(
        jornada=jornada, movimiento_especial=objeto if es_movimiento else None,
        numero=calidad["revision"], motivo=motivo,
        kilometros=medicion["kilometros"], calidad=calidad,
    )
    return objeto


def consolidar_movimiento(movimiento, sesiones=None, motivo="CIERRE"):
    registros = RegistroUbicacion.objects.filter(
        jornada=movimiento.jornada, repartidor=movimiento.repartidor,
        registrada_en__gt=movimiento.iniciada_en, registrada_en__lt=movimiento.finalizada_en,
    ).order_by("registrada_en", "id").values_list(
        "latitud", "longitud", "precision_metros", "velocidad_metros_segundo", "registrada_en",
    ).iterator(chunk_size=1000)

    def puntos():
        yield (movimiento.latitud_inicio, movimiento.longitud_inicio, None, None, movimiento.iniciada_en)
        yield from registros
        yield (movimiento.latitud_fin, movimiento.longitud_fin, None, None, movimiento.finalizada_en)

    medicion = medir_puntos(puntos())
    # Los extremos son eventos operativos, no registros GPS del lote.
    medicion["puntos_considerados"] = max(0, medicion["puntos_considerados"] - 2)
    medicion["segundos_operativos"] = (movimiento.finalizada_en - movimiento.iniciada_en).total_seconds()
    return _guardar_medicion(movimiento, medicion, sesiones, movimiento.finalizada_en, motivo)


def consolidar_jornada(jornada, sesiones=None, motivo="CIERRE"):
    from apps.jornadas.kilometraje import medir_jornada
    from apps.solicitudes.models import MovimientoEnvioEspecial
    from apps.solicitudes.opciones import EstadoMovimientoEnvioEspecial

    # Un manifiesto completo de la jornada también confirma sus prefijos especiales.
    if comprobar_sesiones(jornada, sesiones, jornada.finalizada_en)[0]:
        for movimiento in MovimientoEnvioEspecial.objects.select_for_update().filter(
            jornada=jornada, estado=EstadoMovimientoEnvioEspecial.FINALIZADO,
            calidad_kilometraje__estado__in=("SIN_VERIFICAR", "PENDIENTE_SINCRONIZACION"),
        ):
            prefijo = list(RegistroUbicacion.objects.filter(
                jornada=jornada, registrada_en__lte=movimiento.finalizada_en,
            ).values("sesion_gps").annotate(ultima_secuencia=Max("secuencia")))
            consolidar_movimiento(movimiento, prefijo, motivo)

    return _guardar_medicion(jornada, medir_jornada(jornada, jornada.finalizada_en), sesiones, jornada.finalizada_en, motivo)


def revisar_mediciones_pendientes(jornada):
    from apps.jornadas.opciones import EstadoJornada
    from apps.solicitudes.models import MovimientoEnvioEspecial
    from apps.solicitudes.opciones import EstadoMovimientoEnvioEspecial

    movimientos = MovimientoEnvioEspecial.objects.select_for_update().filter(
        jornada=jornada, estado=EstadoMovimientoEnvioEspecial.FINALIZADO,
        calidad_kilometraje__estado="PENDIENTE_SINCRONIZACION",
    )
    for movimiento in movimientos:
        sesiones = movimiento.calidad_kilometraje["sesiones_gps"]
        if comprobar_sesiones(jornada, sesiones, movimiento.finalizada_en)[0]:
            consolidar_movimiento(movimiento, sesiones, "GPS_TARDIO")
    if jornada.estado == EstadoJornada.FINALIZADA and jornada.calidad_kilometraje.get("estado") == "PENDIENTE_SINCRONIZACION":
        sesiones = jornada.calidad_kilometraje["sesiones_gps"]
        if comprobar_sesiones(jornada, sesiones, jornada.finalizada_en)[0]:
            consolidar_jornada(jornada, sesiones, "GPS_TARDIO")
