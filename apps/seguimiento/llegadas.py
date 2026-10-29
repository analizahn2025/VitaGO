"""Llegadas a la próxima parada usando únicamente capturas GPS propias.

La detección ocurre después del commit del lote GPS: las transiciones bloquean
solicitud -> motorista -> jornada, mientras la recepción bloquea motorista ->
jornada. No se consultan proveedores ni se completan recolecciones o entregas.
"""

from datetime import timedelta
from itertools import groupby

from django.conf import settings
from django.db import transaction
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.jornadas.models import JornadaRepartidor
from apps.jornadas.opciones import EstadoJornada
from apps.repartidores.habilitacion import tiene_rol_operativo_repartidor
from apps.repartidores.models import Repartidor
from apps.repartidores.opciones import EstadoOperativoRepartidor
from apps.seguimiento.distancias import distancia_kilometros
from apps.seguimiento.models import RegistroUbicacion
from apps.solicitudes.models import AsignacionSolicitud, EventoSolicitud, Solicitud
from apps.solicitudes.opciones import (
    EstadoAsignacionSolicitud,
    EstadoSolicitud,
    TipoEventoSolicitud,
)
from apps.usuarios.opciones import EstadoUsuario


_MAXIMO_PUNTOS_MUESTRA = 60
_TRANSICIONES_LLEGADA = {
    "RECOLECCION": (
        EstadoSolicitud.HACIA_RECOLECCION,
        EstadoSolicitud.EN_RECOLECCION,
        TipoEventoSolicitud.HACIA_RECOLECCION,
        TipoEventoSolicitud.LLEGADA_RECOLECCION,
    ),
    "ENTREGA": (
        EstadoSolicitud.EN_TRANSITO,
        EstadoSolicitud.EN_DESTINO,
        TipoEventoSolicitud.EN_TRANSITO,
        TipoEventoSolicitud.LLEGADA_DESTINO,
    ),
}


def presentar_llegada(evento):
    """Aviso navegable estable; evento_id permite deduplicar la pantalla móvil."""
    es_recoleccion = evento.tipo == TipoEventoSolicitud.LLEGADA_RECOLECCION
    tipo_parada = "RECOLECCION" if es_recoleccion else "ENTREGA"
    return {
        "evento_id": str(evento.pk),
        "solicitud_id": str(evento.solicitud_id),
        "estado": evento.metadatos.get(
            "estado_nuevo",
            EstadoSolicitud.EN_RECOLECCION if es_recoleccion else EstadoSolicitud.EN_DESTINO,
        ),
        "tipo_parada": tipo_parada,
        "detectada_en": evento.creado_en.isoformat(),
        "fuente": "GPS" if evento.metadatos.get("llegada_gps") else "MANUAL",
        "pantalla": tipo_parada,
        "ruta": f"/solicitudes/{evento.solicitud_id}",
    }


def obtener_llegada_actual(repartidor, paradas):
    """Recupera una llegada vigente si el cliente perdió la respuesta del POST."""
    if not paradas:
        return None
    proxima = paradas[0]
    tipo = "ENTREGA" if proxima["tipo"] == "ENVIO_ESPECIAL" else proxima["tipo"]
    transicion = _TRANSICIONES_LLEGADA.get(tipo)
    if transicion is None or proxima["estado_solicitud"] != transicion[1]:
        return None
    asignacion = AsignacionSolicitud.objects.filter(
        solicitud_id=proxima["solicitud_id"],
        repartidor=repartidor,
        estado=EstadoAsignacionSolicitud.ACTIVA,
    ).first()
    if asignacion is None:
        return None
    evento = EventoSolicitud.objects.filter(
        solicitud_id=proxima["solicitud_id"],
        repartidor=repartidor,
        tipo=transicion[3],
        creado_en__gte=asignacion.asignada_en,
    ).order_by("-creado_en", "-id").first()
    return presentar_llegada(evento) if evento else None


def programar_deteccion_llegada(usuario, repartidor_id, jornada_id, resultado):
    """Un fallo posterior no invalida capturas que ya quedaron confirmadas."""
    resultado.setdefault("llegadas_detectadas", [])
    if not getattr(settings, "LLEGADAS_AUTOMATICAS_HABILITADAS", True):
        return

    def detectar_despues_del_commit():
        llegada = detectar_llegada(usuario, repartidor_id, jornada_id)
        if llegada is not None:
            resultado["llegadas_detectadas"].append(llegada)

    transaction.on_commit(detectar_despues_del_commit, robust=True)


def _inicio_desplazamiento(solicitud, asignacion, jornada, tipo_evento):
    # La fecha de la asignación nueva invalida cualquier permanencia del
    # motorista anterior, incluso al continuar directamente hacia el destino.
    evento = EventoSolicitud.objects.filter(
        solicitud=solicitud,
        tipo=tipo_evento,
    ).order_by("-creado_en", "-id").first()
    limites = [jornada.iniciada_en, asignacion.asignada_en]
    if asignacion.aceptada_en is not None:
        limites.append(asignacion.aceptada_en)
    if evento is not None:
        limites.append(evento.creado_en)
    return max(limites)


def _prueba_permanencia(repartidor, jornada, asignacion, parada, desde, ahora):
    radio = settings.RADIO_LLEGADA_METROS
    permanencia = settings.PERMANENCIA_LLEGADA_SEGUNDOS
    minimo_puntos = settings.MINIMO_PUNTOS_LLEGADA
    precision_maxima = settings.PRECISION_LLEGADA_MAXIMA_METROS
    antiguedad_maxima = settings.ANTIGUEDAD_LLEGADA_MAXIMA_SEGUNDOS
    intervalo_maximo = settings.INTERVALO_GPS_MAXIMO_SEGUNDOS
    ventana = max(120, permanencia + 2 * antiguedad_maxima)
    registros = list(
        RegistroUbicacion.objects.filter(
            repartidor=repartidor,
            jornada=jornada,
            registrada_en__gte=max(desde, ahora - timedelta(seconds=ventana)),
        )
        .order_by("-registrada_en", "-id")[:_MAXIMO_PUNTOS_MUESTRA]
    )
    if not registros:
        return None
    ultimo = registros[0]
    if not (
        0 <= (ahora - ultimo.registrada_en).total_seconds() <= antiguedad_maxima
        and 0 <= (ahora - ultimo.creado_en).total_seconds() <= antiguedad_maxima
    ):
        return None

    ubicacion = parada["ubicacion"]
    racha = []
    distancias = []
    # No se filtran previamente puntos imprecisos/fuera del radio: deben
    # interrumpir la permanencia en lugar de unir visitas independientes.
    for _, grupo in groupby(registros, key=lambda punto: punto.registrada_en):
        simultaneos = list(grupo)
        distancias_grupo = []
        for punto in simultaneos:
            retraso = (punto.creado_en - punto.registrada_en).total_seconds()
            if (
                punto.precision_metros is None
                or punto.precision_metros > precision_maxima
                or not 0 <= retraso <= antiguedad_maxima
                or punto.creado_en > ahora
            ):
                return _resumir_racha(
                    racha, distancias, asignacion, jornada, desde,
                    radio, precision_maxima, minimo_puntos, permanencia,
                )
            distancia = 1000 * distancia_kilometros(
                punto.latitud, punto.longitud, ubicacion.latitud, ubicacion.longitud,
            )
            if distancia > radio:
                return _resumir_racha(
                    racha, distancias, asignacion, jornada, desde,
                    radio, precision_maxima, minimo_puntos, permanencia,
                )
            distancias_grupo.append(distancia)

        punto = max(simultaneos, key=lambda registro: registro.creado_en)
        if racha:
            anterior = racha[-1]
            intervalo = (anterior.registrada_en - punto.registrada_en).total_seconds()
            if intervalo > intervalo_maximo:
                break
            if anterior.sesion_gps is not None and punto.sesion_gps is not None:
                if (
                    anterior.sesion_gps != punto.sesion_gps
                    or anterior.secuencia - punto.secuencia != 1
                ):
                    break
        racha.append(punto)
        distancias.append(max(distancias_grupo))

    return _resumir_racha(
        racha, distancias, asignacion, jornada, desde,
        radio, precision_maxima, minimo_puntos, permanencia,
    )


def _resumir_racha(
    racha, distancias, asignacion, jornada, desde,
    radio, precision_maxima, minimo_puntos, permanencia,
):
    if len(racha) < minimo_puntos:
        return None
    ultimo, primero = racha[0], racha[-1]
    duracion = (ultimo.registrada_en - primero.registrada_en).total_seconds()
    duracion_servidor = (
        max(punto.creado_en for punto in racha)
        - min(punto.creado_en for punto in racha)
    ).total_seconds()
    # Un único lote no puede fabricar diez segundos de espera cambiando las
    # fechas del teléfono: también deben transcurrir en el reloj del servidor.
    if duracion < permanencia or duracion_servidor < permanencia:
        return None
    return {
        "primer_registro_id": str(primero.pk),
        "ultimo_registro_id": str(ultimo.pk),
        "cantidad_puntos": len(racha),
        "permanencia_captura_segundos": round(duracion, 3),
        "permanencia_servidor_segundos": round(duracion_servidor, 3),
        "distancia_metros": round(distancias[0], 3),
        "distancia_maxima_metros": round(max(distancias), 3),
        "radio_metros": float(radio),
        "precision_maxima_metros": float(precision_maxima),
        "precision_observada_maxima_metros": float(max(punto.precision_metros for punto in racha)),
        "jornada_id": str(jornada.pk),
        "asignacion_id": str(asignacion.pk),
        "iniciada_en": primero.registrada_en.isoformat(),
        "ultima_captura_en": ultimo.registrada_en.isoformat(),
        "desde_estado_en": desde.isoformat(),
    }


def detectar_llegada(usuario, repartidor_id, jornada_id):
    """Detecta como máximo una llegada; la transición bloqueada es idempotente."""
    from apps.rutas.selectores import obtener_paradas_operativas

    if not getattr(settings, "LLEGADAS_AUTOMATICAS_HABILITADAS", True):
        return None
    candidato = Repartidor.objects.filter(pk=repartidor_id, usuario_id=usuario.pk).first()
    if candidato is None:
        return None
    paradas = obtener_paradas_operativas(candidato)
    if not paradas or paradas[0]["tipo"] not in _TRANSICIONES_LLEGADA:
        return None
    proxima = paradas[0]
    transicion = _TRANSICIONES_LLEGADA[proxima["tipo"]]
    if proxima["estado_solicitud"] != transicion[0]:
        return None

    try:
        with transaction.atomic():
            solicitud = (
                Solicitud.objects.select_for_update(of=("self",), no_key=True)
                .select_related("empresa__pais")
                .filter(pk=proxima["solicitud_id"])
                .first()
            )
            if solicitud is None or solicitud.repartidor_asignado_id != candidato.pk:
                return None
            repartidor = (
                Repartidor.objects.select_for_update(of=("self",))
                .select_related("usuario", "empresa__pais")
                .filter(
                    pk=candidato.pk,
                    usuario_id=usuario.pk,
                    usuario__estado=EstadoUsuario.ACTIVO,
                    activo=True,
                    # Reanudar desde pausa puede dejar AVAILABLE aunque una
                    # solicitud ya siga IN_TRANSIT. No exigir otro inicio.
                    estado_operativo__in=(
                        EstadoOperativoRepartidor.DISPONIBLE,
                        EstadoOperativoRepartidor.EN_RUTA,
                    ),
                )
                .first()
            )
            if repartidor is None or not tiene_rol_operativo_repartidor(repartidor):
                return None
            jornada = JornadaRepartidor.objects.select_for_update(of=("self",)).filter(
                pk=jornada_id, repartidor=repartidor, estado=EstadoJornada.ACTIVA,
            ).first()
            if jornada is None:
                return None
            ahora = timezone.now()
            from apps.solicitudes.vigencia import exigir_vigencia_solicitud

            exigir_vigencia_solicitud(solicitud, ahora)
            from apps.jornadas.horario import jornada_vigente
            if not jornada_vigente(jornada, ahora):
                return None
            vigentes = obtener_paradas_operativas(repartidor)
            if not vigentes:
                return None
            parada = vigentes[0]
            if (
                parada["solicitud_id"] != solicitud.pk
                or parada["tipo"] != proxima["tipo"]
                or parada["estado_solicitud"] != transicion[0]
                or solicitud.estado != transicion[0]
                or parada["ubicacion"] is None
            ):
                return None
            asignacion = AsignacionSolicitud.objects.filter(
                solicitud=solicitud,
                repartidor=repartidor,
                estado=EstadoAsignacionSolicitud.ACTIVA,
            ).first()
            if asignacion is None:
                return None
            desde = _inicio_desplazamiento(solicitud, asignacion, jornada, transicion[2])
            prueba = _prueba_permanencia(
                repartidor, jornada, asignacion, parada, desde, ahora,
            )
            if prueba is None:
                return None
            ultimo = RegistroUbicacion.objects.get(pk=prueba["ultimo_registro_id"])
            from apps.solicitudes.servicios import cambiar_estado_solicitud

            cambiar_estado_solicitud(
                repartidor.usuario,
                solicitud.pk,
                {
                    "estado_destino": transicion[1],
                    "latitud": ultimo.latitud,
                    "longitud": ultimo.longitud,
                },
                llegada_gps=prueba,
            )
            evento = EventoSolicitud.objects.filter(
                solicitud=solicitud,
                repartidor=repartidor,
                tipo=transicion[3],
            ).order_by("-creado_en", "-id").first()
            return presentar_llegada(evento) if evento else None
    except (APIException, Http404):
        # Una revocación, cierre o cambio operativo concurrente no convierte la
        # recepción GPS ya confirmada en un error ni autoriza otra transición.
        return None
