"""Última posición de motoristas en jornada, para administración autorizada."""

from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Exists, IntegerField, OuterRef, Subquery
from django.db.models.functions import Coalesce
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.jornadas.models import AlmuerzoJornada, JornadaRepartidor
from apps.seguimiento.models import RegistroUbicacion
from apps.solicitudes.models import Solicitud
from apps.solicitudes.opciones import ESTADOS_SOLICITUD_ACTIVOS
from apps.usuarios.opciones import EstadoUsuario
from apps.usuarios.servicios import obtener_alcances_permiso


def listar_motoristas_en_jornada(usuario, filtros, ahora):
    alcances = obtener_alcances_permiso(usuario, "repartidor.ver_ubicacion")
    if not (alcances.global_ or alcances.empresas):
        raise PermissionDenied('Requiere "repartidor.ver_ubicacion" con alcance de empresa completa o global.')
    if settings.MODO_APLICACION == "EXTERNO":
        if not alcances.global_:
            raise PermissionDenied("La ubicación de la flota Network requiere alcance global.")
        if "empresa_id" in filtros:
            raise ValidationError({"empresa_id": "Network utiliza flota global, sin empresa cliente en el perfil del motorista."})

    jornadas = JornadaRepartidor.objects.filter(
        estado="ACTIVA", iniciada_en__lte=ahora, cierre_programado_en__gt=ahora,
        repartidor__activo=True, repartidor__usuario__estado=EstadoUsuario.ACTIVO,
    )
    if not alcances.global_:
        jornadas = jornadas.filter(repartidor__empresa_id__in=alcances.empresas)
    if settings.MODO_APLICACION == "EXTERNO":
        jornadas = jornadas.filter(repartidor__empresa__isnull=True)
    else:
        jornadas = jornadas.filter(repartidor__empresa__isnull=False)
    if filtros.get("empresa_id"):
        jornadas = jornadas.filter(repartidor__empresa_id=filtros["empresa_id"])
    if filtros.get("repartidor_id"):
        jornadas = jornadas.filter(repartidor_id=filtros["repartidor_id"])
    if filtros.get("estado_operativo"):
        jornadas = jornadas.filter(repartidor__estado_operativo=filtros["estado_operativo"])

    ultima = RegistroUbicacion.objects.filter(
        jornada_id=OuterRef("pk"), repartidor_id=OuterRef("repartidor_id"),
        registrada_en__gte=OuterRef("iniciada_en"), registrada_en__lte=ahora,
    ).order_by("-registrada_en", "-id")
    servicios = Solicitud.objects.filter(
        repartidor_asignado_id=OuterRef("repartidor_id"), estado__in=ESTADOS_SOLICITUD_ACTIVOS,
    ).order_by().values("repartidor_asignado_id").annotate(cantidad=Count("id")).values("cantidad")
    almuerzos = AlmuerzoJornada.objects.filter(jornada_id=OuterRef("pk"), finalizada_en__isnull=True)
    jornadas = jornadas.annotate(
        ultima_ubicacion_id=Subquery(ultima.values("pk")[:1]),
        solicitudes_activas=Coalesce(Subquery(servicios, output_field=IntegerField()), 0),
        en_almuerzo=Exists(almuerzos),
    )
    if "con_servicios" in filtros:
        jornadas = jornadas.filter(solicitudes_activas__gt=0) if filtros["con_servicios"] else jornadas.filter(solicitudes_activas=0)
    if "en_almuerzo" in filtros:
        jornadas = jornadas.filter(en_almuerzo=filtros["en_almuerzo"])
    return jornadas.select_related("repartidor__usuario").only(
        "id", "repartidor_id", "fecha_operativa", "iniciada_en", "cierre_programado_en",
        "repartidor__id", "repartidor__usuario_id", "repartidor__empresa_id", "repartidor__estado_operativo",
        "repartidor__usuario__id", "repartidor__usuario__nombres", "repartidor__usuario__apellidos",
    ).order_by("repartidor__usuario__nombres", "repartidor__usuario__apellidos", "repartidor_id")


def _estado_ubicacion(ubicacion, ahora):
    if ubicacion is None:
        return "SIN_UBICACION"
    if ubicacion.registrada_en < ahora - timedelta(seconds=settings.ANTIGUEDAD_GPS_ASIGNACION_SEGUNDOS):
        return "DESACTUALIZADA"
    if ubicacion.precision_metros is None:
        return "SIN_PRECISION"
    if ubicacion.precision_metros > settings.PRECISION_GPS_ASIGNACION_METROS:
        return "BAJA_PRECISION"
    return "ACTUALIZADA"


def construir_posiciones_motoristas(jornadas, ahora):
    """Consulta solo los puntos seleccionados de esta página, sin N+1 ni historial."""
    ids = [j.ultima_ubicacion_id for j in jornadas if j.ultima_ubicacion_id]
    ubicaciones = RegistroUbicacion.objects.in_bulk(ids)
    resultados = []
    for jornada in jornadas:
        repartidor = jornada.repartidor
        ubicacion = ubicaciones.get(jornada.ultima_ubicacion_id)
        estado = _estado_ubicacion(ubicacion, ahora)
        resultados.append({
            "repartidor_id": repartidor.pk, "usuario_id": repartidor.usuario_id,
            "nombre": repartidor.usuario.get_full_name(), "empresa_id": repartidor.empresa_id,
            "jornada_id": jornada.pk, "fecha_operativa": jornada.fecha_operativa,
            "iniciada_en": jornada.iniciada_en, "cierre_programado_en": jornada.cierre_programado_en,
            "estado_operativo": repartidor.estado_operativo, "en_almuerzo": jornada.en_almuerzo,
            "solicitudes_activas": jornada.solicitudes_activas,
            "tiene_servicios_activos": jornada.solicitudes_activas > 0,
            "ubicacion": ubicacion, "estado_ubicacion": estado,
            "ubicacion_vigente": estado == "ACTUALIZADA",
            "antiguedad_segundos": round((ahora - ubicacion.registrada_en).total_seconds(), 3) if ubicacion else None,
        })
    return resultados
