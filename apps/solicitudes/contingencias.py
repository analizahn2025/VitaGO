"""Suspensiones y cierre del día corporativo, con trazabilidad e idempotencia."""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.jornadas.models import JornadaRepartidor
from apps.notificaciones.models import NotificacionUsuario
from apps.repartidores.models import Repartidor
from apps.solicitudes.models import AsignacionSolicitud, EventoSolicitud, MovimientoEnvioEspecial, Solicitud
from apps.solicitudes.opciones import (
    ESTADOS_SOLICITUD_ACTIVOS, EstadoAsignacionSolicitud, EstadoMovimientoEnvioEspecial,
    EstadoSolicitud, TipoEventoSolicitud,
)
from apps.solicitudes.vigencia import limite_dia_operativo
from apps.usuarios.opciones import EstadoUsuario


registro = logging.getLogger("vitago.api")
ESTADOS_CON_PAQUETE = (EstadoSolicitud.RECOLECTADA, EstadoSolicitud.EN_TRANSITO, EstadoSolicitud.EN_DESTINO)
ESTADOS_ABIERTOS = (EstadoSolicitud.PENDIENTE, *ESTADOS_SOLICITUD_ACTIVOS)


def _notificar(solicitud, evento, tipo, titulo, mensaje, usuarios):
    for usuario_id in {identificador for identificador in usuarios if identificador is not None}:
        NotificacionUsuario.objects.get_or_create(
            usuario_id=usuario_id, evento=evento,
            defaults={"solicitud": solicitud, "tipo": tipo, "titulo": titulo, "mensaje": mensaje},
        )


def cerrar_tramo_interrumpido(solicitud, repartidor, instante, motivo):
    """Sin coordenadas inventadas: la calidad queda sin verificar hasta recibir GPS."""
    from apps.seguimiento.sincronizacion import consolidar_movimiento

    movimiento = MovimientoEnvioEspecial.objects.select_for_update().filter(
        solicitud=solicitud, repartidor=repartidor, estado=EstadoMovimientoEnvioEspecial.ACTIVO,
    ).first()
    if movimiento is None:
        return
    from apps.seguimiento.models import RegistroUbicacion
    RegistroUbicacion.objects.filter(
        repartidor=repartidor, jornada_id=movimiento.jornada_id,
        registrada_en__gte=movimiento.iniciada_en, registrada_en__lte=instante,
    ).filter(Q(movimiento_envio_especial__isnull=True) | Q(movimiento_envio_especial=movimiento)).update(
        movimiento_envio_especial=movimiento, es_operativo=True,
    )
    movimiento.estado = EstadoMovimientoEnvioEspecial.FINALIZADO
    movimiento.finalizada_en = max(instante, movimiento.iniciada_en)
    movimiento.motivo_cierre = motivo
    movimiento.save(update_fields=("estado", "finalizada_en", "motivo_cierre", "actualizado_en"))
    consolidar_movimiento(movimiento, None, motivo)


@transaction.atomic
def cerrar_solicitud_vencida(solicitud_id, ahora=None):
    if settings.MODO_APLICACION != "CORPORATIVO":
        return False
    ahora = ahora or timezone.now()
    solicitud = Solicitud.objects.select_for_update(of=("self",)).select_related("empresa__pais").get(pk=solicitud_id)
    if solicitud.estado not in ESTADOS_ABIERTOS:
        return False
    corte = limite_dia_operativo(solicitud.creado_en, solicitud.empresa)
    if ahora < corte:
        return False
    repartidor = Repartidor.objects.select_for_update(of=("self",)).filter(pk=solicitud.repartidor_asignado_id).first()
    estado_anterior = solicitud.estado
    if repartidor is not None:
        cerrar_tramo_interrumpido(solicitud, repartidor, corte, "FIN_DIA")
    solicitud.estado = EstadoSolicitud.ENTREGA_FALLIDA if estado_anterior in ESTADOS_CON_PAQUETE else EstadoSolicitud.RECOLECCION_FALLIDA
    solicitud.reasignacion_pendiente = False
    solicitud.cerrada_en = corte
    solicitud.motivo_cierre = "FIN_DIA"
    solicitud.save(update_fields=("estado", "reasignacion_pendiente", "cerrada_en", "motivo_cierre", "actualizado_en"))
    from apps.solicitudes.servicios import _cerrar_asignacion
    _cerrar_asignacion(solicitud, repartidor, None, solicitud.estado, corte)
    evento = EventoSolicitud.objects.create(
        solicitud=solicitud, tipo=TipoEventoSolicitud.CIERRE_AUTOMATICO, repartidor=repartidor,
        metadatos={"motivo": "FIN_DIA", "estado_anterior": estado_anterior, "estado_nuevo": solicitud.estado,
                   "cierre_efectivo_en": corte.isoformat(), "ejecutado_en": ahora.isoformat()},
    )
    _notificar(solicitud, evento, "SERVICIO_NO_ENTREGADO", "Servicio cerrado al terminar el día",
               f"La solicitud {solicitud.numero} no se completó dentro del día operativo.",
               [solicitud.solicitada_por_id, repartidor.usuario_id if repartidor else None])
    if repartidor is not None:
        from apps.rutas.models import VersionRuta
        from apps.rutas.servicios import sincronizar_ruta
        sincronizar_ruta(repartidor, VersionRuta.Motivo.CAMBIO_ESTADO, finalizada_en=corte)
    return True


@transaction.atomic
def retirar_servicio_por_suspension(solicitud_id, usuario_administrador=None, ahora=None):
    if settings.MODO_APLICACION != "CORPORATIVO":
        return False
    ahora = ahora or timezone.now()
    solicitud = Solicitud.objects.select_for_update(of=("self",)).select_related("empresa__pais").get(pk=solicitud_id)
    if solicitud.estado not in ESTADOS_SOLICITUD_ACTIVOS or not solicitud.repartidor_asignado_id:
        return False
    if ahora >= limite_dia_operativo(solicitud.creado_en, solicitud.empresa):
        return cerrar_solicitud_vencida(solicitud.pk, ahora)
    repartidor = Repartidor.objects.select_for_update(of=("self",)).select_related("usuario").get(pk=solicitud.repartidor_asignado_id)
    # Se revalida dentro del bloqueo: una recuperación de cuenta no retira servicios.
    from apps.usuarios.models import Usuario
    if Usuario.objetos.filter(pk=repartidor.usuario_id, estado=EstadoUsuario.ACTIVO).exists():
        return False
    asignacion = AsignacionSolicitud.objects.select_for_update().get(solicitud=solicitud, estado=EstadoAsignacionSolicitud.ACTIVA)
    cerrar_tramo_interrumpido(solicitud, repartidor, ahora, "SUSPENSION")
    asignacion.estado = EstadoAsignacionSolicitud.REASIGNADA
    asignacion.finalizada_en = ahora
    asignacion.motivo = "Retirada por suspensión o desactivación del usuario."
    asignacion.save(update_fields=("estado", "finalizada_en", "motivo", "actualizado_en"))
    estado_anterior = solicitud.estado
    solicitud.repartidor_asignado = None
    solicitud.reasignacion_pendiente = True
    if estado_anterior not in ESTADOS_CON_PAQUETE:
        solicitud.estado = EstadoSolicitud.PENDIENTE
        solicitud.llegada_recoleccion_en = None
    solicitud.save(update_fields=("repartidor_asignado", "reasignacion_pendiente", "estado", "llegada_recoleccion_en", "actualizado_en"))
    evento = EventoSolicitud.objects.create(
        solicitud=solicitud, tipo=TipoEventoSolicitud.REASIGNACION_PENDIENTE,
        realizado_por=usuario_administrador, repartidor=repartidor,
        metadatos={"motivo": "SUSPENSION", "estado_anterior": estado_anterior,
                   "repartidor_anterior_id": str(repartidor.pk),
                   "traspaso_fisico_fuera_app": estado_anterior in ESTADOS_CON_PAQUETE},
    )
    _notificar(solicitud, evento, "REASIGNACION_PENDIENTE", "Servicio pendiente de reasignación",
               f"La solicitud {solicitud.numero} requiere otro motorista. El traspaso físico se coordina fuera de la app.",
               [solicitud.solicitada_por_id, getattr(usuario_administrador, "pk", None), repartidor.usuario_id])
    from apps.repartidores.capacidad import sincronizar_capacidad_repartidor
    from apps.solicitudes.servicios import _registrar_cambio_operativo_repartidor, programar_reintento_pendientes
    from apps.rutas.models import VersionRuta
    from apps.rutas.servicios import sincronizar_ruta
    sincronizar_capacidad_repartidor(repartidor, usuario_administrador, "Retirada por suspensión.")
    _registrar_cambio_operativo_repartidor(repartidor, usuario_administrador,
        estado_nuevo="OUT_OF_SERVICE", motivo="Usuario suspendido o inactivo.")
    sincronizar_ruta(repartidor, VersionRuta.Motivo.REASIGNACION)
    programar_reintento_pendientes(solicitud.empresa_id)
    return True


def procesar_suspension(usuario_id, usuario_administrador=None):
    """Corre después del commit; no introduce inversión usuario → motorista."""
    if settings.MODO_APLICACION != "CORPORATIVO":
        return 0
    ids = list(Solicitud.objects.filter(repartidor_asignado__usuario_id=usuario_id,
        estado__in=ESTADOS_SOLICITUD_ACTIVOS).values_list("pk", flat=True))
    return sum(retirar_servicio_por_suspension(pk, usuario_administrador) for pk in ids)


def programar_suspension(usuario_id, administrador):
    if settings.MODO_APLICACION != "CORPORATIVO":
        return
    def despues_del_commit():
        try:
            procesar_suspension(usuario_id, administrador)
        except Exception:
            # La tarea local recupera también contingencias interrumpidas.
            registro.exception("Pendiente recuperar servicios de un motorista suspendido: %s", usuario_id)
    transaction.on_commit(despues_del_commit)


@transaction.atomic
def cerrar_jornada_vencida(jornada_id, ahora=None):
    if settings.MODO_APLICACION != "CORPORATIVO":
        return False
    ahora = ahora or timezone.now()
    previa = JornadaRepartidor.objects.select_related("repartidor__empresa__pais").get(pk=jornada_id)
    repartidor = Repartidor.objects.select_for_update(of=("self",)).get(pk=previa.repartidor_id)
    jornada = JornadaRepartidor.objects.select_for_update(of=("self",)).get(pk=jornada_id)
    if jornada.estado != "ACTIVA" or repartidor.empresa_id is None:
        return False
    corte = limite_dia_operativo(jornada.iniciada_en, previa.repartidor.empresa)
    if ahora < corte or AsignacionSolicitud.objects.filter(repartidor=repartidor, estado=EstadoAsignacionSolicitud.ACTIVA).exists():
        return False
    from apps.jornadas.servicios import _calcular_resumen, _registrar_estado_repartidor
    resumen = _calcular_resumen(jornada, corte)
    jornada.estado = "FINALIZADA"
    jornada.finalizada_en = corte
    for campo, valor in resumen.items():
        setattr(jornada, campo, valor)
    jornada.save(update_fields=("estado", "finalizada_en", *resumen.keys(), "actualizado_en"))
    from apps.seguimiento.sincronizacion import consolidar_jornada
    consolidar_jornada(jornada, None, "FIN_DIA")
    _registrar_estado_repartidor(repartidor, None, estado_nuevo="OFFLINE", motivo="Fin del día operativo.")
    from apps.rutas.models import VersionRuta
    from apps.rutas.servicios import sincronizar_ruta
    sincronizar_ruta(repartidor, VersionRuta.Motivo.CIERRE_JORNADA, cerrar=True, finalizada_en=corte)
    return True


def procesar_cierre_diario(ahora=None):
    """Recupera también días anteriores; no toca Network ni terminales históricos."""
    resultado = {"solicitudes_cerradas": 0, "servicios_retirados": 0, "jornadas_cerradas": 0}
    if settings.MODO_APLICACION != "CORPORATIVO":
        return resultado
    ahora = ahora or timezone.now()
    def procesar_unidad(campo, funcion, *argumentos):
        try:
            resultado[campo] += int(funcion(*argumentos))
        except Exception:
            resultado["errores"] = resultado.get("errores", 0) + 1
            registro.exception("No se pudo completar %s para %s", campo, argumentos[0])

    from apps.organizaciones.models import Empresa
    empresas_con_servicios = Solicitud.objects.filter(estado__in=ESTADOS_ABIERTOS).values("empresa_id")
    empresas_con_jornadas = JornadaRepartidor.objects.filter(estado="ACTIVA").values("repartidor__empresa_id")
    empresas = Empresa.objects.filter(
        Q(pk__in=empresas_con_servicios) | Q(pk__in=empresas_con_jornadas),
    ).select_related("pais")
    for empresa in empresas.iterator(chunk_size=100):
        try:
            inicio_hoy = limite_dia_operativo(ahora, empresa) - timedelta(days=1)
        except Exception:
            resultado["errores"] = resultado.get("errores", 0) + 1
            registro.exception("No se pudo resolver el día de la empresa %s", empresa.pk)
            continue
        # No bloquear ni recorrer los servicios vigentes de hoy cada minuto.
        consulta = Solicitud.objects.filter(empresa=empresa, estado__in=ESTADOS_ABIERTOS,
            creado_en__lt=inicio_hoy).values_list("pk", flat=True)
        for pk in consulta.iterator(chunk_size=200):
            procesar_unidad("solicitudes_cerradas", cerrar_solicitud_vencida, pk, ahora)
        jornadas = JornadaRepartidor.objects.filter(repartidor__empresa=empresa, estado="ACTIVA",
            iniciada_en__lt=inicio_hoy).values_list("pk", flat=True)
        for pk in jornadas.iterator(chunk_size=200):
            procesar_unidad("jornadas_cerradas", cerrar_jornada_vencida, pk, ahora)
    suspendidos = Solicitud.objects.filter(estado__in=ESTADOS_SOLICITUD_ACTIVOS).exclude(
        repartidor_asignado__usuario__estado=EstadoUsuario.ACTIVO,
    ).exclude(repartidor_asignado__isnull=True).order_by().values_list("repartidor_asignado__usuario_id", flat=True).distinct()
    for usuario_id in suspendidos:
        procesar_unidad("servicios_retirados", procesar_suspension, usuario_id)
    return resultado
