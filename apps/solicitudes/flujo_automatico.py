"""Activa la próxima parada, siempre después de liberar otros bloqueos."""

import logging

from django.db import transaction
from django.http import Http404
from rest_framework.exceptions import APIException, ValidationError

from apps.flota.opciones import EstadoVehiculo, TipoVehiculo
from apps.jornadas.models import JornadaRepartidor
from apps.repartidores.habilitacion import tiene_rol_operativo_repartidor
from apps.repartidores.models import Repartidor
from apps.repartidores.opciones import EstadoOperativoRepartidor
from apps.solicitudes.models import Solicitud
from apps.solicitudes.opciones import EstadoSolicitud
from apps.usuarios.opciones import EstadoUsuario


registro = logging.getLogger("vitago.api")


def exigir_siguiente_parada(solicitud, repartidor, tipo):
    from apps.rutas.selectores import obtener_paradas_operativas

    paradas = obtener_paradas_operativas(repartidor)
    if (not paradas or paradas[0]["solicitud_id"] != solicitud.pk
            or paradas[0]["tipo"] != tipo):
        raise ValidationError({"estado_destino": "Debe completar la parada vigente antes de operar otra."})


def activar_siguiente_servicio(repartidor_id):
    """Idempotente: solicitud → motorista → jornada; activa solo la próxima parada."""
    from apps.rutas.selectores import obtener_paradas_operativas
    from apps.seguimiento.vigencia import posiciones_vigentes
    from apps.solicitudes.servicios import cambiar_estado_solicitud

    candidato = Repartidor.objects.filter(pk=repartidor_id).first()
    if candidato is None:
        return None
    paradas = obtener_paradas_operativas(candidato)
    destinos = {EstadoSolicitud.ASIGNADA: EstadoSolicitud.HACIA_RECOLECCION,
                EstadoSolicitud.RECOLECTADA: EstadoSolicitud.EN_TRANSITO}
    if not paradas or paradas[0]["estado_solicitud"] not in destinos:
        return None
    try:
        with transaction.atomic():
            solicitud = Solicitud.objects.select_for_update(of=("self",), no_key=True).filter(
                pk=paradas[0]["solicitud_id"], repartidor_asignado=candidato,
            ).first()
            if solicitud is None or solicitud.estado not in destinos:
                return None
            repartidor = Repartidor.objects.select_for_update(of=("self",)).select_related(
                "usuario", "empresa__pais", "vehiculo",
            ).filter(
                pk=repartidor_id, activo=True, usuario__estado=EstadoUsuario.ACTIVO,
                estado_operativo__in=(EstadoOperativoRepartidor.DISPONIBLE, EstadoOperativoRepartidor.EN_RUTA),
                vehiculo__estado=EstadoVehiculo.ACTIVO, vehiculo__tipo=TipoVehiculo.MOTOCICLETA,
            ).first()
            if repartidor is None or not tiene_rol_operativo_repartidor(repartidor):
                return None
            jornada = JornadaRepartidor.objects.select_for_update(of=("self",)).filter(
                repartidor=repartidor, estado="ACTIVA",
            ).first()
            from apps.jornadas.horario import jornada_vigente
            if not jornada_vigente(jornada):
                return None
            exigir_siguiente_parada(solicitud, repartidor, paradas[0]["tipo"])
            punto = posiciones_vigentes().filter(repartidor=repartidor, jornada=jornada).first()
            if punto is None:
                return None
            return cambiar_estado_solicitud(repartidor.usuario, solicitud.pk, {
                "estado_destino": destinos[solicitud.estado],
                "latitud": punto.latitud, "longitud": punto.longitud,
            }, automatismo={"fuente": "ACTIVACION_SERVICIO"})
    except (APIException, Http404):
        # Un cambio concurrente o un permiso retirado no autoriza otra etapa.
        return None


def programar_avance_automatico(repartidor_id):
    def avanzar():
        try:
            activar_siguiente_servicio(repartidor_id)
        except Exception:
            registro.exception("No se pudo activar el siguiente servicio; se recuperará con el próximo GPS.")

    transaction.on_commit(avanzar, robust=True)


def presentar_flujo_actual(paradas):
    proxima = paradas[0] if paradas else None
    estado = proxima["estado_solicitud"] if proxima else None
    especial = bool(proxima and proxima["tipo"] == "ENVIO_ESPECIAL")
    evidencia = {EstadoSolicitud.EN_RECOLECCION: "FOTO_RECOLECCION", EstadoSolicitud.EN_DESTINO: "FOTO_ENTREGA"}.get(estado)
    finalizar_especial = especial and estado == EstadoSolicitud.EN_TRANSITO
    return {
        "modo": "AUTOMATICO", "requiere_aceptacion": False, "permite_elegir_etapa": False,
        "solicitud_id": str(proxima["solicitud_id"]) if proxima else None,
        "tipo_parada": proxima["tipo"] if proxima else None,
        "estado": estado,
        "tramo_id": f'{proxima["solicitud_id"]}:{proxima["tipo"]}' if proxima else None,
        "pantalla": ("SIN_SERVICIOS" if not proxima else "FINALIZAR_ESPECIAL" if finalizar_especial
                     else "RECOLECCION" if estado == EstadoSolicitud.EN_RECOLECCION
                     else "ENTREGA" if estado == EstadoSolicitud.EN_DESTINO else "MAPA"),
        "evidencia_requerida": evidencia,
        "requiere_finalizacion_especial": finalizar_especial,
    }
