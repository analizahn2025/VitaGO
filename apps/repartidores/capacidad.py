"""Carga operativa calculada exclusivamente desde las solicitudes."""

from django.db.models import Count, Exists, F, IntegerField, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce

from apps.flota.opciones import EstadoVehiculo, TipoVehiculo
from apps.repartidores.habilitacion import anotar_rol_operativo, tiene_rol_operativo_repartidor
from apps.repartidores.opciones import CapacidadRepartidor, EstadoOperativoRepartidor
from apps.solicitudes.models import MovimientoEnvioEspecial, Solicitud
from apps.solicitudes.opciones import (
    ESTADOS_SOLICITUD_ACTIVOS,
    EstadoMovimientoEnvioEspecial,
    EstadoSolicitud,
    PrioridadSolicitud,
)
from apps.usuarios.opciones import EstadoUsuario


LIMITE_SOLICITUDES = 5
ESTADOS_PRIORITARIO_EXCLUSIVO = ESTADOS_SOLICITUD_ACTIVOS
ESTADOS_CON_TUBOS_RECOGIDOS = (EstadoSolicitud.RECOLECTADA, EstadoSolicitud.EN_TRANSITO, EstadoSolicitud.EN_DESTINO)


def obtener_carga_tubos(repartidor):
    campos = ("tubos_comprometidos", "tubos_en_transporte", "solicitudes_sin_cantidad_tubos")
    if all(hasattr(repartidor, campo) for campo in campos):
        return {**{campo: getattr(repartidor, campo) for campo in campos}, "solicitudes_activas": repartidor.solicitudes_activas_calculadas}
    return Solicitud.objects.filter(repartidor_asignado=repartidor, estado__in=ESTADOS_SOLICITUD_ACTIVOS).aggregate(
        solicitudes_activas=Count("id"),
        tubos_comprometidos=Coalesce(Sum("cantidad_tubos"), 0),
        tubos_en_transporte=Coalesce(Sum("cantidad_tubos", filter=Q(estado__in=ESTADOS_CON_TUBOS_RECOGIDOS)), 0),
        solicitudes_sin_cantidad_tubos=Count("id", filter=Q(cantidad_tubos__isnull=True)),
    )


def contar_solicitudes_activas(repartidor):
    return Solicitud.objects.filter(
        repartidor_asignado=repartidor,
        estado__in=ESTADOS_SOLICITUD_ACTIVOS,
    ).count()


def calcular_capacidad(cantidad, *, limite_tubos=20, tubos_comprometidos=0, solicitudes_sin_cantidad_tubos=0, **_):
    if cantidad <= 0:
        return CapacidadRepartidor.VACIO
    if cantidad >= LIMITE_SOLICITUDES or tubos_comprometidos >= limite_tubos or solicitudes_sin_cantidad_tubos:
        return CapacidadRepartidor.LLENO
    return CapacidadRepartidor.ESPACIO_DISPONIBLE


def anotar_carga_repartidores(consulta):
    carga = Solicitud.objects.filter(repartidor_asignado_id=OuterRef("pk"), estado__in=ESTADOS_SOLICITUD_ACTIVOS).order_by().values("repartidor_asignado_id")
    anotaciones = {
        "tubos_comprometidos": Sum("cantidad_tubos"),
        "tubos_en_transporte": Sum("cantidad_tubos", filter=Q(estado__in=ESTADOS_CON_TUBOS_RECOGIDOS)),
        "solicitudes_sin_cantidad_tubos": Count("id", filter=Q(cantidad_tubos__isnull=True)),
    }
    prioritarias = Solicitud.objects.filter(
        repartidor_asignado_id=OuterRef("pk"),
        prioridad=PrioridadSolicitud.PRIORITARIA,
        estado__in=ESTADOS_PRIORITARIO_EXCLUSIVO,
    )
    especiales = MovimientoEnvioEspecial.objects.filter(
        repartidor_id=OuterRef("pk"),
        estado=EstadoMovimientoEnvioEspecial.ACTIVO,
    )
    return anotar_rol_operativo(consulta).annotate(**{
        campo: Coalesce(Subquery(carga.annotate(valor=expresion).values("valor"), output_field=IntegerField()), 0)
        for campo, expresion in anotaciones.items()
    }).annotate(
        solicitudes_activas_calculadas=Count(
            "solicitudes_asignadas",
            filter=Q(solicitudes_asignadas__estado__in=ESTADOS_SOLICITUD_ACTIVOS),
            distinct=True,
        ),
        lleva_prioritario_exclusivo=Exists(prioritarias),
        tiene_especial_activo=Exists(especiales),
    )


def filtrar_repartidores_disponibles(consulta, cantidad_tubos=1):
    """Aplica la misma elegibilidad a listados y asignación automática."""
    return consulta.filter(
        activo=True,
        usuario__estado=EstadoUsuario.ACTIVO,
        tiene_rol_operativo_vigente=True,
        solicitudes_activas_calculadas__lt=LIMITE_SOLICITUDES,
        solicitudes_sin_cantidad_tubos=0,
        limite_tubos__gte=F("tubos_comprometidos") + cantidad_tubos,
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


def puede_recibir_solicitudes(repartidor, cantidad=None, *, carga=None):
    if cantidad is None:
        cantidad = getattr(repartidor, "solicitudes_activas_calculadas", None)
    if cantidad is None:
        cantidad = contar_solicitudes_activas(repartidor)
    if cantidad >= LIMITE_SOLICITUDES:
        return False
    carga = obtener_carga_tubos(repartidor) if carga is None else carga
    if carga["solicitudes_sin_cantidad_tubos"] or carga["tubos_comprometidos"] >= repartidor.limite_tubos:
        return False
    if not repartidor.activo or repartidor.usuario.estado != EstadoUsuario.ACTIVO:
        return False
    if not tiene_rol_operativo_repartidor(repartidor):
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
    from apps.repartidores.operacion import registrar_operacion_repartidor

    return registrar_operacion_repartidor(repartidor, usuario, motivo=motivo)
