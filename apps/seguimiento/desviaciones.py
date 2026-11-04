"""Vigilancia de la próxima parada, con tolerancia, permanencia y avisos únicos.

Usa la geometría vigente de Routes API sin consultas adicionales ni guardar
distancias/duraciones del proveedor. Contraste revisado con:
https://cloud.google.com/maps-platform/terms/maps-service-terms?utm_campaign=gmp_git_agentskills_v1
"""

from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.jornadas.horario import jornada_vigente
from apps.jornadas.models import JornadaRepartidor
from apps.notificaciones.models import NotificacionUsuario
from apps.repartidores.habilitacion import tiene_rol_operativo_repartidor
from apps.repartidores.models import Repartidor
from apps.rutas.models import RutaRepartidor
from apps.rutas.ruta_vial import calculo_reutilizable, firma_paradas
from apps.rutas.selectores import obtener_paradas_operativas
from apps.rutas.tramos import presentar_tramos
from apps.seguimiento.distancias import distancia_kilometros
from apps.seguimiento.geometria import decodificar_polilinea, distancia_a_polilinea_metros
from apps.seguimiento.models import DesviacionRuta, RegistroUbicacion
from apps.solicitudes.models import AsignacionSolicitud, EventoSolicitud, Solicitud
from apps.usuarios.models import RolUsuario, Usuario


ESTADOS_VIGILADOS = {"RECOLECCION": "GOING_TO_PICKUP", "ENTREGA": "IN_TRANSIT"}


def presentar_desviacion(alerta):
    return {"id": str(alerta.pk), "evento_id": str(alerta.evento_id), "tipo": "DESVIACION_RUTA",
            "solicitud_id": str(alerta.solicitud_id), "tipo_parada": alerta.tipo_parada,
            "detectada_en": alerta.detectada_en.isoformat(), "finalizada_en": alerta.finalizada_en.isoformat() if alerta.finalizada_en else None,
            "titulo": "Desvío de ruta detectado", "mensaje": "Te has mantenido fuera del recorrido previsto. Revisa tu ruta y reporta cualquier incidencia.",
            "ruta": f"/solicitudes/{alerta.solicitud_id}"}


def obtener_desviacion_actual(repartidor, paradas):
    if not paradas or paradas[0]["estado_solicitud"] != ESTADOS_VIGILADOS.get(paradas[0]["tipo"]):
        return None
    alerta = DesviacionRuta.objects.filter(repartidor=repartidor, finalizada_en__isnull=True,
        jornada__estado="ACTIVA", calculo__estado="CALCULADA", calculo__expira_en__gt=timezone.now(),
        solicitud_id=paradas[0]["solicitud_id"], tipo_parada=paradas[0]["tipo"]).select_related("jornada").first()
    return presentar_desviacion(alerta) if alerta and jornada_vigente(alerta.jornada) else None


def cerrar_desviaciones_contexto(repartidor, paradas, *, cerrar=False, instante=None, motivo=None):
    """Quien sincroniza ya mantiene bloqueado al motorista; no se bloquean solicitudes."""
    abiertas = DesviacionRuta.objects.filter(repartidor=repartidor, finalizada_en__isnull=True)
    if not cerrar and paradas and paradas[0]["estado_solicitud"] == ESTADOS_VIGILADOS.get(paradas[0]["tipo"]):
        abiertas = abiertas.exclude(solicitud_id=paradas[0]["solicitud_id"], tipo_parada=paradas[0]["tipo"])
    ahora = instante or timezone.now()
    # El corte recuperado puede ser anterior a ahora; nunca anterior al aviso.
    from django.db.models import F
    from django.db.models.functions import Greatest
    return abiertas.update(finalizada_en=Greatest(F("detectada_en"), ahora),
                            motivo_cierre=motivo or ("FIN_JORNADA" if cerrar else "CAMBIO_ETAPA"), actualizado_en=timezone.now())


def _racha(registros, puntos, ahora, *, regreso=False):
    seleccionados, anterior = [], None
    permanencia = max(1, settings.DESVIACION_PERMANENCIA_SEGUNDOS / 4) if regreso else settings.DESVIACION_PERMANENCIA_SEGUNDOS
    for registro in registros:  # Más reciente primero; un punto inválido rompe la continuidad.
        precision = registro.precision_metros
        edad = (ahora - registro.registrada_en).total_seconds()
        if precision is None or precision > settings.DESVIACION_PRECISION_MAXIMA_METROS or edad < 0:
            break
        if anterior:
            segundos = (anterior.registrada_en - registro.registrada_en).total_seconds()
            if not 0 < segundos <= settings.INTERVALO_GPS_MAXIMO_SEGUNDOS or anterior.sesion_gps != registro.sesion_gps:
                break
            velocidad = distancia_kilometros(anterior.latitud, anterior.longitud, registro.latitud, registro.longitud) * 1000 / segundos
            if velocidad > settings.VELOCIDAD_GPS_MAXIMA_METROS_SEGUNDO:
                break
        distancia = distancia_a_polilinea_metros(registro.latitud, registro.longitud, puntos)
        cumple = (distancia + float(precision) <= settings.DESVIACION_RADIO_REGRESO_METROS) if regreso else (
            distancia - float(precision) > settings.DESVIACION_RADIO_METROS)
        if not cumple:
            break
        seleccionados.append(registro)
        if len(seleccionados) >= settings.DESVIACION_MINIMO_PUNTOS and (
            seleccionados[0].registrada_en - registro.registrada_en).total_seconds() >= permanencia:
            return registro.registrada_en
        anterior = registro
    return None


def _destinatarios(repartidor):
    alcance = Q(tipo_alcance="GLOBAL")
    if repartidor.empresa_id:
        alcance |= Q(tipo_alcance="EMPRESA", empresa_id=repartidor.empresa_id)
    roles = RolUsuario.objetos.filter(alcance, activo=True, rol__activo=True,
        rol__asignaciones_permisos__activo=True, rol__asignaciones_permisos__permiso__activo=True)
    usuarios = Usuario.objetos.filter(estado="ACTIVO")
    permiso = Q(es_superusuario=True)
    ambos = Q()
    for codigo in ("repartidor.ver_ubicacion", "solicitud.ver"):
        ambos &= Q(pk__in=roles.filter(rol__asignaciones_permisos__permiso__codigo=codigo).values("usuario_id"))
    return set(usuarios.filter(permiso | ambos).values_list("pk", flat=True)) | {repartidor.usuario_id}


def detectar_desviacion(usuario, repartidor_id, jornada_id):
    if not settings.DESVIACIONES_AUTOMATICAS_HABILITADAS:
        return None
    candidato = Repartidor.objects.filter(pk=repartidor_id, usuario=usuario).first()
    if candidato is None:
        return None
    paradas = obtener_paradas_operativas(candidato)
    if not paradas:
        return None
    # Mismo orden de bloqueo que llegadas: solicitud -> motorista -> jornada.
    with transaction.atomic():
        solicitud = Solicitud.objects.select_for_update(of=("self",)).filter(pk=paradas[0]["solicitud_id"]).first()
        repartidor = Repartidor.objects.select_for_update(of=("self",)).select_related("usuario").filter(
            pk=repartidor_id, usuario=usuario, activo=True, usuario__estado="ACTIVO", estado_operativo__in=("AVAILABLE", "ON_ROUTE")).first()
        if repartidor is None or not tiene_rol_operativo_repartidor(repartidor):
            return None
        jornada = JornadaRepartidor.objects.select_for_update().filter(pk=jornada_id, repartidor=repartidor).first()
        ahora = timezone.now()
        paradas = obtener_paradas_operativas(repartidor)
        cerrar_desviaciones_contexto(repartidor, paradas)
        if not jornada_vigente(jornada, ahora) or not paradas or solicitud is None:
            return None
        proxima = paradas[0]
        if proxima["solicitud_id"] != solicitud.pk or solicitud.repartidor_asignado_id != repartidor.pk or (
            solicitud.estado != ESTADOS_VIGILADOS.get(proxima["tipo"])):
            return None
        ruta = RutaRepartidor.objects.filter(repartidor=repartidor, jornada=jornada, estado="ACTIVA").first()
        firma = firma_paradas(paradas)
        calculo = calculo_reutilizable(ruta, firma, ahora)
        tramos = presentar_tramos(calculo, firma, paradas)
        if not tramos["desglose_disponible"] or not tramos["tramos"]:
            cerrar_desviaciones_contexto(repartidor, [], motivo="RUTA_NO_DISPONIBLE")
            return None
        tramo = tramos["tramos"][0]
        puntos = decodificar_polilinea(tramo["polilinea_codificada"])
        if not puntos or tramo["sin_desplazamiento"]:
            cerrar_desviaciones_contexto(repartidor, [], motivo="RUTA_NO_DISPONIBLE")
            return None
        asignacion = AsignacionSolicitud.objects.filter(solicitud=solicitud, repartidor=repartidor, estado="ACTIVA", aceptada_en__isnull=False).first()
        if asignacion is None:
            return None
        fase = "HACIA_RECOLECCION" if proxima["tipo"] == "RECOLECCION" else "EN_TRANSITO"
        ultimo_inicio = EventoSolicitud.objects.filter(solicitud=solicitud, repartidor=repartidor, tipo=fase,
            creado_en__gte=asignacion.asignada_en).order_by("-creado_en").values_list("creado_en", flat=True).first()
        ventana = settings.DESVIACION_PERMANENCIA_SEGUNDOS + 2*settings.INTERVALO_GPS_MAXIMO_SEGUNDOS
        desde = max(calculo.calculada_en, asignacion.aceptada_en, ultimo_inicio or asignacion.aceptada_en,
                    ahora - timedelta(seconds=ventana))
        registros = list(RegistroUbicacion.objects.filter(repartidor=repartidor, jornada=jornada,
            registrada_en__gte=desde, registrada_en__lte=ahora).order_by("-registrada_en", "-id")[:300])
        if not registros or (ahora - registros[0].registrada_en).total_seconds() > settings.DESVIACION_ANTIGUEDAD_MAXIMA_SEGUNDOS:
            return None
        alerta = DesviacionRuta.objects.filter(repartidor=repartidor, finalizada_en__isnull=True).first()
        if alerta and alerta.calculo_id != calculo.pk:
            alerta.finalizada_en, alerta.motivo_cierre = ahora, "CAMBIO_RUTA"
            alerta.save(update_fields=("finalizada_en", "motivo_cierre", "actualizado_en"))
            alerta = None
        if alerta:
            if _racha(registros, puntos, ahora, regreso=True):
                alerta.finalizada_en, alerta.motivo_cierre = ahora, "REGRESO_RUTA"
                alerta.save(update_fields=("finalizada_en", "motivo_cierre", "actualizado_en"))
            return presentar_desviacion(alerta)
        iniciada = _racha(registros, puntos, ahora)
        if iniciada is None:
            return None
        identificador = uuid4()
        evento = EventoSolicitud.objects.create(solicitud=solicitud, repartidor=repartidor, tipo="DESVIACION_RUTA",
            latitud=registros[0].latitud, longitud=registros[0].longitud,
            metadatos={"desviacion_id": str(identificador), "fuente": "GPS", "tipo_parada": proxima["tipo"]})
        alerta = DesviacionRuta.objects.create(id=identificador, repartidor=repartidor, jornada=jornada,
            solicitud=solicitud, calculo=calculo, evento=evento, tipo_parada=proxima["tipo"], iniciada_en=iniciada, detectada_en=ahora)
        aviso = presentar_desviacion(alerta)
        NotificacionUsuario.objects.bulk_create([NotificacionUsuario(usuario_id=usuario_id, solicitud=solicitud,
            evento=evento, tipo="DESVIACION_RUTA", titulo=aviso["titulo"],
            mensaje=f'{repartidor.usuario.nombres}: solicitud {solicitud.numero}. {aviso["mensaje"]}') for usuario_id in _destinatarios(repartidor)])
        return aviso


def programar_deteccion_desviacion(usuario, repartidor_id, jornada_id, resultado):
    resultado.setdefault("alertas_ruta", [])

    def despues_del_commit():
        aviso = detectar_desviacion(usuario, repartidor_id, jornada_id)
        if aviso is not None:
            resultado["alertas_ruta"].append(aviso)

    transaction.on_commit(despues_del_commit, robust=True)
