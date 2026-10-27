"""Paradas operativas derivadas de las asignaciones vigentes del motorista."""

from django.http import Http404
from rest_framework.exceptions import PermissionDenied

from apps.jornadas.models import JornadaRepartidor
from apps.jornadas.opciones import EstadoJornada
from apps.repartidores.models import Repartidor
from apps.rutas.models import ParadaVersionRuta, RutaRepartidor, VersionRuta
from apps.rutas.ordenamiento import ordenar_paradas
from apps.solicitudes.models import Solicitud
from apps.solicitudes.opciones import (
    ESTADOS_SOLICITUD_ACTIVOS,
    EstadoAsignacionSolicitud,
    EstadoSolicitud,
    ModalidadSolicitud,
)
from apps.usuarios.servicios import usuario_tiene_permiso


ESTADOS_ANTES_RECOLECCION = {
    EstadoSolicitud.ASIGNADA,
    EstadoSolicitud.HACIA_RECOLECCION,
    EstadoSolicitud.EN_RECOLECCION,
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
        "cantidad_tubos": solicitud.cantidad_tubos,
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


def obtener_solicitudes_operativas(repartidor):
    return list(
        Solicitud.objects.filter(
            repartidor_asignado=repartidor,
            estado__in=ESTADOS_SOLICITUD_ACTIVOS,
            asignaciones__estado=EstadoAsignacionSolicitud.ACTIVA,
            asignaciones__repartidor=repartidor,
        )
        .select_related("origen", "destino")
        .distinct()
    )


def crear_paradas_operativas(solicitudes, orden_previo=(), *, punto_gps=None):
    paradas = []
    for solicitud in sorted(solicitudes, key=lambda s: (s.asignada_en or s.creado_en, str(s.pk))):
        paradas.extend(_paradas_de_solicitud(solicitud))
    paradas = ordenar_paradas(paradas, orden_previo, punto_gps=punto_gps)
    for orden, parada in enumerate(paradas, start=1):
        parada["orden"] = orden

    return paradas


def obtener_paradas_operativas(repartidor):
    """Lee el orden guardado, sin replanificar por GPS ni escribir versiones."""
    ultima = VersionRuta.objects.filter(
        ruta__repartidor=repartidor, ruta__estado=RutaRepartidor.Estado.ACTIVA,
    ).order_by("-numero").values("pk")[:1]
    orden_previo = ParadaVersionRuta.objects.filter(version_id=ultima).order_by("orden").values_list(
        "solicitud_id", "tipo",
    )
    return crear_paradas_operativas(obtener_solicitudes_operativas(repartidor), orden_previo)


def obtener_mi_ruta(usuario):
    """Lectura operativa: nunca modifica versiones ni consulta proveedores."""
    from apps.rutas.presentacion import presentar_mapa_integrado
    from apps.rutas.ruta_vial import presentar_ruta_vial
    from apps.seguimiento.llegadas import obtener_llegada_actual
    from apps.solicitudes.flujo_automatico import presentar_flujo_actual

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
    ruta_vial = presentar_ruta_vial(ruta, paradas, version_actual)
    return {
        "repartidor_id": repartidor.id,
        "jornada_id": jornada_id,
        "ruta_id": ruta.id if ruta else None,
        "version_actual": version_actual,
        "orden_tipo": "CERCANIA_GPS",
        "ruta_calculada": ruta_vial["estado"] == "CALCULADA",
        "ruta_vial": ruta_vial,
        "mapa": presentar_mapa_integrado(paradas, ruta_vial),
        "proxima_parada": paradas[0] if paradas else None,
        "llegada_actual": obtener_llegada_actual(repartidor, paradas),
        "flujo_actual": presentar_flujo_actual(paradas),
        "paradas": paradas,
    }
