"""Sincronización transaccional del historial de paradas operativas."""

from django.db import transaction
from django.utils import timezone

from apps.jornadas.models import JornadaRepartidor
from apps.jornadas.opciones import EstadoJornada
from apps.rutas.models import ParadaVersionRuta, RutaRepartidor, VersionRuta
from apps.rutas.ordenamiento import clave_parada
from apps.rutas.selectores import crear_paradas_operativas, obtener_solicitudes_operativas
from apps.seguimiento.vigencia import posiciones_vigentes


def _firma_parada(parada):
    ubicacion = parada["ubicacion"]
    return (
        str(parada["solicitud_id"]),
        parada["tipo"],
        str(ubicacion.id) if ubicacion else None,
        parada["destino_especial"],
        str(ubicacion.latitud) if ubicacion else None,
        str(ubicacion.longitud) if ubicacion else None,
    )


def _firma_persistida(parada):
    return (
        str(parada.solicitud_id),
        parada.tipo,
        str(parada.ubicacion_id) if parada.ubicacion_id else None,
        parada.destino_especial,
        str(parada.latitud_ubicacion) if parada.ubicacion_id else None,
        str(parada.longitud_ubicacion) if parada.ubicacion_id else None,
    )


def sincronizar_ruta(repartidor, motivo, *, jornada=None, cerrar=False, finalizada_en=None):
    """Guarda una versión solo si cambió la secuencia de paradas.

    Quien llama debe mantener bloqueada la fila del motorista y una
    transacción abierta, igual que los casos de uso de asignación y jornada.
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("La ruta debe sincronizarse dentro de una transacción.")

    solicitudes = obtener_solicitudes_operativas(repartidor)
    ruta = (
        RutaRepartidor.objects.select_for_update()
        .filter(repartidor=repartidor, estado=RutaRepartidor.Estado.ACTIVA)
        .first()
    )
    if ruta is None and not solicitudes:
        return None

    if jornada is None and not cerrar:
        jornada = JornadaRepartidor.objects.filter(
            repartidor=repartidor, estado=EstadoJornada.ACTIVA
        ).first()
    if ruta is None:
        ruta = RutaRepartidor.objects.create(repartidor=repartidor, jornada=jornada)
    elif ruta.jornada_id is None and jornada is not None:
        ruta.jornada = jornada
        ruta.save(update_fields=("jornada", "actualizado_en"))

    ultima = ruta.versiones.order_by("-numero").first()
    anteriores = list(ultima.paradas.order_by("orden")) if ultima else []
    orden_previo = [(str(parada.solicitud_id), parada.tipo) for parada in anteriores]
    paradas = crear_paradas_operativas(solicitudes, orden_previo)
    cambio_paradas = {clave_parada(p) for p in paradas} != set(orden_previo)
    punto_gps = None
    # Replanificar solo ante altas/bajas o una parada completada. Cambiar GPS,
    # consultar/calcular y llegar sin completar la foto no cambian el orden.
    if solicitudes and (ultima is None or cambio_paradas):
        posicion = posiciones_vigentes().filter(repartidor=repartidor).first()
        if posicion is not None:
            punto_gps = (posicion.latitud, posicion.longitud)
    if punto_gps is not None:
        paradas = crear_paradas_operativas(solicitudes, orden_previo, punto_gps=punto_gps)
    firma_actual = [_firma_parada(parada) for parada in paradas]
    firma_anterior = [_firma_persistida(parada) for parada in anteriores] if ultima else None
    if firma_actual != firma_anterior:
        version = VersionRuta.objects.create(
            ruta=ruta,
            numero=ultima.numero + 1 if ultima else 1,
            motivo=VersionRuta.Motivo.INICIAL if ultima is None else motivo,
        )
        ParadaVersionRuta.objects.bulk_create([
            ParadaVersionRuta(
                version=version,
                solicitud_id=parada["solicitud_id"],
                orden=parada["orden"],
                tipo=parada["tipo"],
                numero_solicitud=parada["numero_solicitud"],
                prioridad=parada["prioridad"],
                modalidad=parada["modalidad"],
                estado_solicitud=parada["estado_solicitud"],
                ubicacion=parada["ubicacion"],
                nombre_ubicacion=(
                    parada["ubicacion"].nombre if parada["ubicacion"] else None
                ),
                direccion_ubicacion=(
                    parada["ubicacion"].direccion if parada["ubicacion"] else None
                ),
                latitud_ubicacion=(
                    parada["ubicacion"].latitud if parada["ubicacion"] else None
                ),
                longitud_ubicacion=(
                    parada["ubicacion"].longitud if parada["ubicacion"] else None
                ),
                destino_especial=parada["destino_especial"],
                presentacion_ruta=parada["presentacion_ruta"],
            )
            for parada in paradas
        ])

    if cerrar or (not paradas and ruta.jornada_id is None):
        ruta.estado = RutaRepartidor.Estado.FINALIZADA
        ruta.finalizada_en = finalizada_en or timezone.now()
        ruta.save(update_fields=("estado", "finalizada_en", "actualizado_en"))
    return ruta
