"""Consultas contextuales y autorizadas para seguimiento operativo."""

from django.conf import settings
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.jornadas.opciones import EstadoJornada
from apps.seguimiento.models import RegistroUbicacion
from apps.seguimiento.vigencia import posiciones_vigentes
from apps.repartidores.models import Repartidor
from apps.solicitudes.models import AsignacionSolicitud
from apps.solicitudes.opciones import EstadoAsignacionSolicitud, EstadoSolicitud
from apps.solicitudes.selectores import obtener_solicitud_autorizada
from apps.usuarios.servicios import usuario_tiene_permiso


ESTADOS_TERMINALES = {
    EstadoSolicitud.ENTREGADA, EstadoSolicitud.CANCELADA,
    EstadoSolicitud.RECOLECCION_FALLIDA, EstadoSolicitud.ENTREGA_FALLIDA,
}


def _diagnosticar_captura_gps(repartidor):
    """Muestra acotada de capturas propias; no mide los intervalos entre POST."""
    capturas = list(
        RegistroUbicacion.objects.filter(
            repartidor=repartidor,
            jornada__repartidor=repartidor,
            jornada__estado=EstadoJornada.ACTIVA,
        ).order_by("-registrada_en", "-id").values_list("registrada_en", flat=True)[:60]
    )
    capturas.reverse()
    intervalos = [
        (siguiente - anterior).total_seconds()
        for anterior, siguiente in zip(capturas, capturas[1:])
        if siguiente > anterior
    ]
    umbral = settings.INTERVALO_GPS_MAXIMO_SEGUNDOS
    fuera_umbral = sum(intervalo > umbral for intervalo in intervalos)
    return {
        "muestra_puntos": len(capturas),
        "intervalos_evaluados": len(intervalos),
        "intervalos_fuera_umbral": fuera_umbral,
        "intervalo_maximo_observado_segundos": (
            round(max(intervalos), 3) if intervalos else None
        ),
        "requiere_ajuste_captura": bool(fuera_umbral),
        "mensaje": (
            "Se detectaron intervalos de captura GPS superiores al umbral. "
            "Revisa la captura en la aplicación; aumentar la frecuencia de envío "
            "de los lotes no recupera puntos que no fueron capturados."
            if fuera_umbral else None
        ),
        "umbral_segundos": umbral,
    }


def obtener_configuracion_gps(usuario):
    try:
        repartidor = Repartidor.objects.select_related("empresa__pais").get(usuario=usuario, activo=True)
    except Repartidor.DoesNotExist as error:
        raise Http404("El usuario no posee un perfil activo de motorista.") from error
    if not usuario_tiene_permiso(usuario, "repartidor.registrar_ubicacion", empresa=repartidor.empresa):
        raise PermissionDenied('No tiene el permiso requerido: "repartidor.registrar_ubicacion".')
    return {
        "hora_servidor": timezone.now().isoformat(),
        "zona_horaria_operativa": (
            repartidor.empresa.pais.zona_horaria_predeterminada
            if repartidor.empresa_id else settings.TIME_ZONE
        ),
        "intervalo_captura_movimiento_segundos": settings.INTERVALO_GPS_CAPTURA_MOVIMIENTO_SEGUNDOS,
        "intervalo_captura_detenido_segundos": settings.INTERVALO_GPS_CAPTURA_DETENIDO_SEGUNDOS,
        "intervalo_envio_segundos": settings.INTERVALO_GPS_ENVIO_SEGUNDOS,
        "tamano_maximo_lote": 200,
        "antiguedad_maxima_asignacion_segundos": settings.ANTIGUEDAD_GPS_ASIGNACION_SEGUNDOS,
        "precision_maxima_asignacion_metros": settings.PRECISION_GPS_ASIGNACION_METROS,
        "asignacion_requiere_gps_vigente": settings.ASIGNACION_REQUIERE_GPS_VIGENTE,
        "intervalo_maximo_medicion_segundos": settings.INTERVALO_GPS_MAXIMO_SEGUNDOS,
        "cobertura_minima_porcentaje": settings.COBERTURA_GPS_MINIMA_PORCENTAJE,
        "diagnostico_captura": _diagnosticar_captura_gps(repartidor),
        "llegada_automatica": {
            "habilitada": settings.LLEGADAS_AUTOMATICAS_HABILITADAS,
            "radio_metros": settings.RADIO_LLEGADA_METROS,
            "permanencia_minima_segundos": settings.PERMANENCIA_LLEGADA_SEGUNDOS,
            "minimo_puntos": settings.MINIMO_PUNTOS_LLEGADA,
            "precision_maxima_metros": settings.PRECISION_LLEGADA_MAXIMA_METROS,
            "antiguedad_maxima_segundos": settings.ANTIGUEDAD_LLEGADA_MAXIMA_SEGUNDOS,
            "solo_proxima_parada": True,
            "destino_especial_sin_coordenadas_manual": True,
        },
    }


def obtener_seguimiento_solicitud(usuario, solicitud_id):
    solicitud = obtener_solicitud_autorizada(usuario, solicitud_id)
    if not usuario_tiene_permiso(
        usuario, "solicitud.ver_seguimiento",
        empresa=solicitud.empresa, sucursal=solicitud.sucursal,
    ):
        raise PermissionDenied(
            'No tiene el permiso requerido: "solicitud.ver_seguimiento".'
        )

    disponible = bool(
        solicitud.repartidor_asignado_id and solicitud.estado not in ESTADOS_TERMINALES
    )
    ubicacion = None
    if disponible:
        asignacion = AsignacionSolicitud.objects.filter(
            solicitud=solicitud,
            repartidor_id=solicitud.repartidor_asignado_id,
            estado=EstadoAsignacionSolicitud.ACTIVA,
            aceptada_en__isnull=False,
        ).first()
        if asignacion:
            ubicacion = RegistroUbicacion.objects.filter(
                repartidor_id=solicitud.repartidor_asignado_id,
                es_operativo=True,
                registrada_en__gte=asignacion.aceptada_en,
                registrada_en__lte=timezone.now(),
            ).order_by("-registrada_en", "-id").first()

    return {
        "solicitud_id": solicitud.id,
        "estado": solicitud.estado,
        "seguimiento_disponible": disponible,
        "ubicacion": ubicacion,
        "ubicacion_vigente": bool(ubicacion and posiciones_vigentes().filter(pk=ubicacion.pk).exists()),
    }
