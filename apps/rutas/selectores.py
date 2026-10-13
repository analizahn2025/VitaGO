"""Paradas operativas derivadas de las asignaciones vigentes del motorista."""

from django.http import Http404
from rest_framework.exceptions import PermissionDenied

from apps.jornadas.models import JornadaRepartidor
from apps.jornadas.opciones import EstadoJornada
from apps.repartidores.models import Repartidor
from apps.solicitudes.models import Solicitud
from apps.solicitudes.opciones import (
    ESTADOS_SOLICITUD_ACTIVOS,
    EstadoAsignacionSolicitud,
    EstadoSolicitud,
    ModalidadSolicitud,
    PrioridadSolicitud,
)
from apps.usuarios.servicios import usuario_tiene_permiso


ESTADOS_ANTES_RECOLECCION = {
    EstadoSolicitud.ASIGNADA,
    EstadoSolicitud.HACIA_RECOLECCION,
    EstadoSolicitud.EN_RECOLECCION,
}
ESTADOS_DESPUES_RECOLECCION = {
    EstadoSolicitud.RECOLECTADA,
    EstadoSolicitud.EN_TRANSITO,
    EstadoSolicitud.EN_DESTINO,
}


def _obtener_repartidor_propio(usuario):
    try:
        repartidor = Repartidor.objects.select_related("empresa").get(
            usuario=usuario,
            activo=True,
        )
    except Repartidor.DoesNotExist as error:
        raise Http404(
            "El usuario no posee un perfil activo de motorista."
        ) from error
    if not usuario_tiene_permiso(
        usuario,
        "solicitud.ver_asignadas",
        empresa=repartidor.empresa,
    ):
        raise PermissionDenied(
            'No tiene el permiso requerido: "solicitud.ver_asignadas".'
        )
    return repartidor


def _crear_parada(solicitud, tipo, ubicacion=None):
    es_especial = solicitud.modalidad == ModalidadSolicitud.ESPECIAL
    return {
        "solicitud_id": solicitud.id,
        "numero_solicitud": solicitud.numero,
        "prioridad": solicitud.prioridad,
        "modalidad": solicitud.modalidad,
        "estado_solicitud": solicitud.estado,
        "tipo": tipo,
        "ubicacion": ubicacion,
        "destino_especial": (
            solicitud.destino_especial if tipo == "ENVIO_ESPECIAL" else None
        ),
        "presentacion_ruta": "SOLO_KILOMETROS" if es_especial else "MAPA",
    }


def _paradas_de_solicitud(solicitud):
    paradas = []
    if solicitud.estado in ESTADOS_ANTES_RECOLECCION:
        paradas.append(_crear_parada(solicitud, "RECOLECCION", solicitud.origen))
    if solicitud.modalidad == ModalidadSolicitud.ESPECIAL:
        paradas.append(_crear_parada(solicitud, "ENVIO_ESPECIAL"))
    else:
        paradas.append(_crear_parada(solicitud, "ENTREGA", solicitud.destino))
    return paradas


def obtener_paradas_operativas(repartidor):
    """Orden provisional compartido por la API y las versiones persistidas."""
    solicitudes = list(
        Solicitud.objects.filter(
            repartidor_asignado=repartidor,
            estado__in=ESTADOS_SOLICITUD_ACTIVOS,
            asignaciones__estado=EstadoAsignacionSolicitud.ACTIVA,
            asignaciones__repartidor=repartidor,
        )
        .select_related("origen", "destino")
        .distinct()
    )
    solicitudes.sort(
        key=lambda solicitud: (
            solicitud.asignada_en or solicitud.creado_en,
            str(solicitud.id),
        )
    )
    exclusivas_recogidas = [
        solicitud
        for solicitud in solicitudes
        if solicitud.estado in ESTADOS_DESPUES_RECOLECCION
        and (
            solicitud.prioridad == PrioridadSolicitud.PRIORITARIA
            or solicitud.modalidad == ModalidadSolicitud.ESPECIAL
        )
    ]
    if exclusivas_recogidas:
        solicitudes = exclusivas_recogidas + [
            solicitud
            for solicitud in solicitudes
            if solicitud not in exclusivas_recogidas
        ]

    paradas = []
    for solicitud in solicitudes:
        paradas.extend(_paradas_de_solicitud(solicitud))
    for orden, parada in enumerate(paradas, start=1):
        parada["orden"] = orden

    return paradas


def obtener_mi_ruta(usuario):
    """Devuelve un orden provisional; no calcula una ruta vial ni ETA."""
    from apps.rutas.models import RutaRepartidor

    repartidor = _obtener_repartidor_propio(usuario)
    jornada_id = (
        JornadaRepartidor.objects.filter(
            repartidor=repartidor,
            estado=EstadoJornada.ACTIVA,
        )
        .values_list("id", flat=True)
        .first()
    )
    ruta = RutaRepartidor.objects.filter(
        repartidor=repartidor,
        estado=RutaRepartidor.Estado.ACTIVA,
    ).first()
    paradas = obtener_paradas_operativas(repartidor)
    version_actual = (
        ruta.versiones.order_by("-numero").values_list("numero", flat=True).first()
        if ruta else None
    )
    return {
        "repartidor_id": repartidor.id,
        "jornada_id": jornada_id,
        "ruta_id": ruta.id if ruta else None,
        "version_actual": version_actual,
        "orden_tipo": "ASIGNACION",
        "ruta_calculada": False,
        "proxima_parada": paradas[0] if paradas else None,
        "paradas": paradas,
    }
