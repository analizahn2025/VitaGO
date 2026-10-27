"""Persistencia común del estado y la capacidad calculada del motorista."""

from django.db import transaction

from apps.repartidores.capacidad import calcular_capacidad, obtener_carga_tubos
from apps.repartidores.models import HistorialEstadoRepartidor


def guardar_cambio_operativo(repartidor, usuario, *, estado_nuevo, capacidad_nueva, motivo, datos_adicionales=None):
    """Guarda y audita cambios ya validados por el caso de uso.

    El llamador debe mantener bloqueada la fila del motorista dentro de una
    transacción. No concede permisos ni acepta capacidad enviada por la API.
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("El cambio operativo requiere una transacción y el motorista bloqueado.")
    estado_anterior = repartidor.estado_operativo
    capacidad_anterior = repartidor.capacidad
    campos = []
    if estado_nuevo != estado_anterior:
        campos.append("estado_operativo")
    if capacidad_nueva != capacidad_anterior:
        campos.append("capacidad")
    if not campos and not datos_adicionales:
        return False
    repartidor.estado_operativo = estado_nuevo
    repartidor.capacidad = capacidad_nueva
    repartidor.save(update_fields=(*campos, "actualizado_en"))
    HistorialEstadoRepartidor.objects.create(
        repartidor=repartidor, estado_anterior=estado_anterior,
        estado_nuevo=estado_nuevo, capacidad_anterior=capacidad_anterior,
        capacidad_nueva=capacidad_nueva, realizado_por=usuario, motivo=motivo,
        datos_adicionales=datos_adicionales or {},
    )
    return True


def registrar_operacion_repartidor(repartidor, usuario, *, motivo, estado_nuevo=None):
    """Recalcula capacidad, conserva el estado si no se indica y devuelve la carga."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("El cambio operativo requiere una transacción y el motorista bloqueado.")
    carga = obtener_carga_tubos(repartidor)
    cantidad = carga["solicitudes_activas"]
    guardar_cambio_operativo(
        repartidor, usuario,
        estado_nuevo=repartidor.estado_operativo if estado_nuevo is None else estado_nuevo,
        capacidad_nueva=calcular_capacidad(cantidad, limite_tubos=repartidor.limite_tubos, **carga), motivo=motivo,
    )
    return cantidad
