"""Paradas por cercanía GPS, con precedencia de recolección y exclusividad."""

from apps.solicitudes.asignacion_automatica import distancia_linea_recta_km
from apps.solicitudes.opciones import EstadoSolicitud, ModalidadSolicitud, PrioridadSolicitud


def clave_parada(parada):
    return str(parada["solicitud_id"]), parada["tipo"]


def ordenar_paradas(paradas, orden_previo=(), *, punto_gps=None):
    """El llamador entrega las paradas en orden de antigüedad estable.

    Solo el sincronizador proporciona GPS. Las lecturas conservan pares
    (solicitud, tipo), sin reagrupar las etapas de una misma solicitud.
    """
    anteriores = [(str(pk), tipo) for pk, tipo in orden_previo]
    posiciones = {clave: indice for indice, clave in enumerate(anteriores)}
    antiguedad = {clave_parada(p): indice for indice, p in enumerate(paradas)}
    pendientes = {clave_parada(p): p for p in paradas}

    def respaldo(clave):
        return posiciones.get(clave, len(posiciones)), antiguedad[clave]

    sin_recoger = {pk for pk, tipo in pendientes if tipo == "RECOLECCION"}
    exclusiva = next((clave for clave in sorted(pendientes, key=respaldo)
                      if clave[0] not in sin_recoger and (
                          pendientes[clave]["prioridad"] == PrioridadSolicitud.PRIORITARIA
                          or pendientes[clave]["modalidad"] == ModalidadSolicitud.ESPECIAL
                      )), None)
    fija = None
    # Fijar una parada en curso, no todo su servicio. PICKED_UP queda disponible
    # para comparar su entrega con otras recolecciones después de guardar la foto.
    candidatas_fijas = sorted(pendientes, key=respaldo)
    if anteriores:
        # También recupera rutas anteriores donde el estado avanzó pero la
        # primera parada persistida aún era la recolección de ese servicio.
        candidatas_fijas.sort(key=lambda clave: clave[0] != anteriores[0][0])
    for clave in candidatas_fijas:
        parada = pendientes.get(clave)
        if parada and (
            (clave[1] == "RECOLECCION" and parada["estado_solicitud"] in {
                EstadoSolicitud.HACIA_RECOLECCION, EstadoSolicitud.EN_RECOLECCION,
            }) or (clave[1] != "RECOLECCION" and parada["estado_solicitud"] in {
                EstadoSolicitud.EN_TRANSITO, EstadoSolicitud.EN_DESTINO,
            })
        ):
            fija = clave
            break

    ordenadas = []
    punto = punto_gps
    while pendientes:
        elegibles = [clave for clave in pendientes
                     if clave[1] == "RECOLECCION" or clave[0] not in sin_recoger]

        def cercania(clave):
            ubicacion = pendientes[clave]["ubicacion"]
            distancia = (distancia_linea_recta_km(*punto, ubicacion.latitud, ubicacion.longitud)
                         if punto is not None and ubicacion else float("inf"))
            return distancia, antiguedad[clave]

        if exclusiva is not None:
            siguiente = exclusiva
        elif fija is not None:
            siguiente = fija
        else:
            siguiente = min(elegibles, key=cercania if punto is not None else respaldo)
        fija = exclusiva = None
        parada = pendientes.pop(siguiente)
        ordenadas.append(parada)
        ubicacion = parada["ubicacion"]
        punto = (ubicacion.latitud, ubicacion.longitud) if punto is not None and ubicacion else None
        if siguiente[1] == "RECOLECCION":
            sin_recoger.remove(siguiente[0])
            if (parada["prioridad"] == PrioridadSolicitud.PRIORITARIA
                    or parada["modalidad"] == ModalidadSolicitud.ESPECIAL):
                exclusiva = next(clave for clave in pendientes if clave[0] == siguiente[0])
    return ordenadas
