"""Política de captura cercana; orienta al cliente sin acreditar una llegada."""

from django.conf import settings

from apps.solicitudes.opciones import EstadoSolicitud


def configuracion_captura_cercana():
    """Frecuencia temporal para la aproximación, incluso con el vehículo detenido."""
    intervalo = settings.INTERVALO_GPS_CERCANO_SEGUNDOS
    return {
        "habilitada": settings.LLEGADAS_AUTOMATICAS_HABILITADAS,
        "radio_activacion_metros": settings.RADIO_CAPTURA_CERCANA_METROS,
        "radio_desactivacion_metros": settings.RADIO_SALIDA_CAPTURA_CERCANA_METROS,
        "intervalo_captura_segundos": min(
            intervalo, settings.INTERVALO_GPS_CAPTURA_MOVIMIENTO_SEGUNDOS,
            settings.INTERVALO_GPS_CAPTURA_DETENIDO_SEGUNDOS,
        ),
        "intervalo_envio_segundos": min(intervalo, settings.INTERVALO_GPS_ENVIO_SEGUNDOS),
        "enviar_al_entrar": True,
        "aplica_detenido": True,
    }


def captura_cercana_para_paradas(paradas, *, jornada_vigente):
    """Solo la próxima parada en desplazamiento puede activar la aproximación."""
    configuracion = configuracion_captura_cercana()
    objetivo = None
    if configuracion["habilitada"] and jornada_vigente and paradas:
        parada = paradas[0]
        estados = {
            "RECOLECCION": EstadoSolicitud.HACIA_RECOLECCION,
            "ENTREGA": EstadoSolicitud.EN_TRANSITO,
        }
        ubicacion = parada["ubicacion"]
        if ubicacion is not None and parada["estado_solicitud"] == estados.get(parada["tipo"]):
            objetivo = {
                "solicitud_id": parada["solicitud_id"],
                "tipo_parada": parada["tipo"],
                "ubicacion_id": ubicacion.pk,
                "latitud": ubicacion.latitud,
                "longitud": ubicacion.longitud,
            }
    return {**configuracion, "habilitada": objetivo is not None, "objetivo": objetivo}
