"""Carga operativa calculada exclusivamente desde las solicitudes."""

from django.db.models import Count, Exists, OuterRef, Q

from apps.flota.opciones import EstadoVehiculo, TipoVehiculo
from apps.repartidores.models import HistorialEstadoRepartidor
from apps.repartidores.opciones import CapacidadRepartidor, EstadoOperativoRepartidor
from apps.solicitudes.models import MovimientoEnvioEspecial, Solicitud
from apps.solicitudes.opciones import (
    ESTADOS_SOLICITUD_ACTIVOS,
    EstadoMovimientoEnvioEspecial,
    PrioridadSolicitud,
)
from apps.usuarios.opciones import EstadoUsuario


LIMITE_SOLICITUDES = 5
ESTADOS_PRIORITARIO_EXCLUSIVO = ESTADOS_SOLICITUD_ACTIVOS


def contar_solicitudes_activas(repartidor):
    return Solicitud.objects.filter(
        repartidor_asignado=repartidor,
        estado__in=ESTADOS_SOLICITUD_ACTIVOS,
    ).count()


def calcular_capacidad(cantidad):
    if cantidad <= 0:
        return CapacidadRepartidor.VACIO
    if cantidad >= LIMITE_SOLICITUDES:
        return CapacidadRepartidor.LLENO
    return CapacidadRepartidor.ESPACIO_DISPONIBLE


def anotar_carga_repartidores(consulta):
    prioritarias = Solicitud.objects.filter(
        repartidor_asignado_id=OuterRef("pk"),
        prioridad=PrioridadSolicitud.PRIORITARIA,
        estado__in=ESTADOS_PRIORITARIO_EXCLUSIVO,
    )
    especiales = MovimientoEnvioEspecial.objects.filter(
        repartidor_id=OuterRef("pk"),
        estado=EstadoMovimientoEnvioEspecial.ACTIVO,
    )
    return consulta.annotate(
        solicitudes_activas_calculadas=Count(
            "solicitudes_asignadas",
            filter=Q(solicitudes_asignadas__estado__in=ESTADOS_SOLICITUD_ACTIVOS),
            distinct=True,
        ),
        lleva_prioritario_exclusivo=Exists(prioritarias),
        tiene_especial_activo=Exists(especiales),
    )


def filtrar_repartidores_disponibles(consulta):
    """Aplica la misma elegibilidad a listados y asignación automática."""
    return consulta.filter(
        activo=True,
        usuario__estado=EstadoUsuario.ACTIVO,
        solicitudes_activas_calculadas__lt=LIMITE_SOLICITUDES,
        lleva_prioritario_exclusivo=False,
        tiene_especial_activo=False,
        vehiculo__estado=EstadoVehiculo.ACTIVO,
        vehiculo__tipo=TipoVehiculo.MOTOCICLETA,
    ).filter(
        Q(estado_operativo=EstadoOperativoRepartidor.DISPONIBLE)
        | Q(
            estado_operativo=EstadoOperativoRepartidor.EN_RUTA,
            solicitudes_activas_calculadas__gt=0,
        )
    )


def puede_recibir_solicitudes(repartidor, cantidad=None):
    if cantidad is None:
        cantidad = getattr(repartidor, "solicitudes_activas_calculadas", None)
    if cantidad is None:
        cantidad = contar_solicitudes_activas(repartidor)
    if cantidad >= LIMITE_SOLICITUDES:
        return False
    if not repartidor.activo or repartidor.usuario.estado != EstadoUsuario.ACTIVO:
        return False
    if repartidor.estado_operativo not in (
        EstadoOperativoRepartidor.DISPONIBLE,
        EstadoOperativoRepartidor.EN_RUTA,
    ):
        return False
    if repartidor.estado_operativo == EstadoOperativoRepartidor.EN_RUTA and not cantidad:
        return False
    if (
        not repartidor.vehiculo_id
        or repartidor.vehiculo.estado != EstadoVehiculo.ACTIVO
        or repartidor.vehiculo.tipo != TipoVehiculo.MOTOCICLETA
    ):
        return False
    prioritario = getattr(repartidor, "lleva_prioritario_exclusivo", None)
    if prioritario is None:
        prioritario = Solicitud.objects.filter(
            repartidor_asignado=repartidor,
            prioridad=PrioridadSolicitud.PRIORITARIA,
            estado__in=ESTADOS_PRIORITARIO_EXCLUSIVO,
        ).exists()
    especial = getattr(repartidor, "tiene_especial_activo", None)
    if especial is None:
        especial = MovimientoEnvioEspecial.objects.filter(
            repartidor=repartidor,
            estado=EstadoMovimientoEnvioEspecial.ACTIVO,
        ).exists()
    return not (prioritario or especial)


def sincronizar_capacidad_repartidor(repartidor, usuario, motivo):
    """Recalcula la capacidad; la fila del motorista debe estar bloqueada."""
    cantidad = contar_solicitudes_activas(repartidor)
    capacidad_nueva = calcular_capacidad(cantidad)
    if repartidor.capacidad == capacidad_nueva:
        return cantidad
    capacidad_anterior = repartidor.capacidad
    repartidor.capacidad = capacidad_nueva
    repartidor.save(update_fields=("capacidad", "actualizado_en"))
    HistorialEstadoRepartidor.objects.create(
        repartidor=repartidor,
        estado_anterior=repartidor.estado_operativo,
        estado_nuevo=repartidor.estado_operativo,
        capacidad_anterior=capacidad_anterior,
        capacidad_nueva=capacidad_nueva,
        realizado_por=usuario,
        motivo=motivo,
    )
    return cantidad
