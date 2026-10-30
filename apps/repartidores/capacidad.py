"""Carga operativa calculada exclusivamente desde las solicitudes."""

from django.db.models import Count, Exists, F, IntegerField, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce

from apps.flota.opciones import EstadoVehiculo, TipoVehiculo
from apps.jornadas.horario import anotar_jornada_y_almuerzo
from apps.repartidores.habilitacion import anotar_rol_operativo, tiene_rol_operativo_repartidor
from apps.repartidores.limites import anotar_limites_repartidores, obtener_limites_repartidor
from apps.repartidores.opciones import CapacidadRepartidor, EstadoOperativoRepartidor
from apps.solicitudes.models import MovimientoEnvioEspecial, Solicitud
from apps.solicitudes.recipientes import TIPOS_RECIPIENTE
from apps.solicitudes.opciones import (
    ESTADOS_SOLICITUD_ACTIVOS,
    EstadoMovimientoEnvioEspecial,
    EstadoSolicitud,
    PrioridadSolicitud,
)
from apps.usuarios.opciones import EstadoUsuario


ESTADOS_PRIORITARIO_EXCLUSIVO = ESTADOS_SOLICITUD_ACTIVOS
ESTADOS_CON_TUBOS_RECOGIDOS = (EstadoSolicitud.RECOLECTADA, EstadoSolicitud.EN_TRANSITO, EstadoSolicitud.EN_DESTINO)


def obtener_carga_recipientes(repartidor):
    campos = tuple(campo for tipo in TIPOS_RECIPIENTE for campo in (f"{tipo}_comprometidos", f"{tipo}_en_transporte", f"solicitudes_sin_cantidad_{tipo}"))
    if all(hasattr(repartidor, campo) for campo in campos):
        return {**{campo: getattr(repartidor, campo) for campo in campos}, "solicitudes_activas": repartidor.solicitudes_activas_calculadas}
    agregados = {"solicitudes_activas": Count("id")}
    for tipo in TIPOS_RECIPIENTE:
        agregados[f"{tipo}_comprometidos"] = Coalesce(Sum(f"cantidad_{tipo}"), 0)
        agregados[f"{tipo}_en_transporte"] = Coalesce(Sum(f"cantidad_{tipo}", filter=Q(estado__in=ESTADOS_CON_TUBOS_RECOGIDOS)), 0)
        agregados[f"solicitudes_sin_cantidad_{tipo}"] = Count("id", filter=Q(**{f"cantidad_{tipo}__isnull": True}))
    return Solicitud.objects.filter(repartidor_asignado=repartidor, estado__in=ESTADOS_SOLICITUD_ACTIVOS).aggregate(**agregados)


def contar_solicitudes_activas(repartidor):
    return Solicitud.objects.filter(
        repartidor_asignado=repartidor,
        estado__in=ESTADOS_SOLICITUD_ACTIVOS,
    ).count()


def calcular_capacidad(cantidad, *, limite_tubos=20, limite_frascos=20, limite_solicitudes=5, tubos_comprometidos=0, frascos_comprometidos=0, solicitudes_sin_cantidad_tubos=0, solicitudes_sin_cantidad_frascos=0, **_):
    if cantidad <= 0:
        return CapacidadRepartidor.VACIO
    sin_espacio = tubos_comprometidos >= limite_tubos and frascos_comprometidos >= limite_frascos
    excedido = tubos_comprometidos > limite_tubos or frascos_comprometidos > limite_frascos
    if cantidad >= limite_solicitudes or sin_espacio or excedido or solicitudes_sin_cantidad_tubos or solicitudes_sin_cantidad_frascos:
        return CapacidadRepartidor.LLENO
    return CapacidadRepartidor.ESPACIO_DISPONIBLE


def anotar_carga_repartidores(consulta):
    carga = Solicitud.objects.filter(repartidor_asignado_id=OuterRef("pk"), estado__in=ESTADOS_SOLICITUD_ACTIVOS).order_by().values("repartidor_asignado_id")
    anotaciones = {}
    for tipo in TIPOS_RECIPIENTE:
        anotaciones[f"{tipo}_comprometidos"] = Sum(f"cantidad_{tipo}")
        anotaciones[f"{tipo}_en_transporte"] = Sum(f"cantidad_{tipo}", filter=Q(estado__in=ESTADOS_CON_TUBOS_RECOGIDOS))
        anotaciones[f"solicitudes_sin_cantidad_{tipo}"] = Count("id", filter=Q(**{f"cantidad_{tipo}__isnull": True}))
    prioritarias = Solicitud.objects.filter(
        repartidor_asignado_id=OuterRef("pk"),
        prioridad=PrioridadSolicitud.PRIORITARIA,
        estado__in=ESTADOS_PRIORITARIO_EXCLUSIVO,
    )
    especiales = MovimientoEnvioEspecial.objects.filter(
        repartidor_id=OuterRef("pk"),
        estado=EstadoMovimientoEnvioEspecial.ACTIVO,
    )
    return anotar_jornada_y_almuerzo(anotar_limites_repartidores(anotar_rol_operativo(consulta))).annotate(**{
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


def filtrar_repartidores_disponibles(consulta, cantidad_tubos=0, cantidad_frascos=0):
    """Aplica la misma elegibilidad a listados y asignación automática."""
    consulta = consulta.filter(
        activo=True,
        usuario__estado=EstadoUsuario.ACTIVO,
        tiene_rol_operativo_vigente=True,
        tiene_jornada_vigente=True,
        en_almuerzo=False,
        solicitudes_activas_calculadas__lt=F("limite_solicitudes_efectivo"),
        solicitudes_sin_cantidad_tubos=0,
        solicitudes_sin_cantidad_frascos=0,
        limite_tubos_efectivo__gte=F("tubos_comprometidos") + cantidad_tubos,
        limite_frascos_efectivo__gte=F("frascos_comprometidos") + cantidad_frascos,
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
    if not (cantidad_tubos or cantidad_frascos):
        consulta = consulta.filter(Q(limite_tubos_efectivo__gt=F("tubos_comprometidos")) | Q(limite_frascos_efectivo__gt=F("frascos_comprometidos")))
    return consulta


def puede_recibir_solicitudes(repartidor, cantidad=None, *, carga=None):
    vigente = getattr(repartidor, "tiene_jornada_vigente", None)
    if vigente is None:
        from apps.jornadas.models import JornadaRepartidor
        from apps.jornadas.horario import jornada_vigente
        vigente = jornada_vigente(JornadaRepartidor.objects.filter(repartidor=repartidor, estado="ACTIVA").first())
    if not vigente:
        return False
    en_almuerzo = getattr(repartidor, "en_almuerzo", None)
    if en_almuerzo is None:
        from apps.jornadas.models import AlmuerzoJornada
        en_almuerzo = AlmuerzoJornada.objects.filter(jornada__repartidor=repartidor, jornada__estado="ACTIVA", finalizada_en__isnull=True).exists()
    if en_almuerzo:
        return False
    limites = obtener_limites_repartidor(repartidor)
    if cantidad is None:
        cantidad = getattr(repartidor, "solicitudes_activas_calculadas", None)
    if cantidad is None:
        cantidad = contar_solicitudes_activas(repartidor)
    if cantidad >= limites["limite_solicitudes"]:
        return False
    carga = obtener_carga_recipientes(repartidor) if carga is None else carga
    if any(carga[f"solicitudes_sin_cantidad_{tipo}"] for tipo in TIPOS_RECIPIENTE):
        return False
    if any(carga[f"{tipo}_comprometidos"] > limites[f"limite_{tipo}"] for tipo in TIPOS_RECIPIENTE):
        return False
    if all(carga[f"{tipo}_comprometidos"] >= limites[f"limite_{tipo}"] for tipo in TIPOS_RECIPIENTE):
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
