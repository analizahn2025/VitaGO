"""Casos de uso transaccionales para jornadas de motoristas."""

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.flota.opciones import EstadoVehiculo, TipoVehiculo
from apps.jornadas.models import JornadaRepartidor
from apps.jornadas.kilometraje import calcular_kilometraje_operativo
from apps.jornadas.opciones import EstadoJornada
from apps.repartidores.models import Repartidor
from apps.repartidores.operacion import registrar_operacion_repartidor
from apps.repartidores.opciones import EstadoOperativoRepartidor
from apps.solicitudes.models import AsignacionSolicitud, Solicitud
from apps.solicitudes.opciones import (
    EstadoAsignacionSolicitud,
    PrioridadSolicitud,
)
from apps.usuarios.opciones import EstadoUsuario
from apps.usuarios.servicios import usuario_tiene_permiso


def _obtener_repartidor_propio_bloqueado(usuario):
    try:
        return (
            Repartidor.objects.select_for_update(of=("self",))
            .select_related("usuario", "empresa", "vehiculo")
            .get(
                usuario=usuario,
                activo=True,
                usuario__estado=EstadoUsuario.ACTIVO,
            )
        )
    except Repartidor.DoesNotExist as error:
        raise Http404(
            "El usuario no posee un perfil activo de motorista."
        ) from error


def _exigir_permiso(usuario, codigo, repartidor):
    if not usuario_tiene_permiso(
        usuario,
        codigo,
        empresa=repartidor.empresa,
    ):
        raise PermissionDenied(f'No tiene el permiso requerido: "{codigo}".')


def _validar_coordenadas(datos):
    latitud = datos.get("latitud")
    longitud = datos.get("longitud")
    if (latitud is None) != (longitud is None):
        raise ValidationError("La latitud y longitud deben enviarse juntas.")
    if latitud is not None and not -90 <= latitud <= 90:
        raise ValidationError({"latitud": "La latitud no es válida."})
    if longitud is not None and not -180 <= longitud <= 180:
        raise ValidationError({"longitud": "La longitud no es válida."})


@transaction.atomic
def iniciar_jornada(usuario, datos_validados):
    _validar_coordenadas(datos_validados)
    repartidor = _obtener_repartidor_propio_bloqueado(usuario)
    _exigir_permiso(usuario, "jornada.iniciar", repartidor)

    if (
        not repartidor.vehiculo_id
        or repartidor.vehiculo.estado != EstadoVehiculo.ACTIVO
        or repartidor.vehiculo.tipo != TipoVehiculo.MOTOCICLETA
    ):
        raise ValidationError(
            {"jornada": "Se requiere un vehículo activo para iniciar jornada."}
        )
    if repartidor.estado_operativo not in (
        EstadoOperativoRepartidor.DESCONECTADO,
        EstadoOperativoRepartidor.DISPONIBLE,
    ):
        raise ValidationError(
            {
                "jornada": (
                    "El motorista debe estar desconectado o disponible para "
                    "iniciar jornada."
                )
            }
        )
    if JornadaRepartidor.objects.filter(
        repartidor=repartidor,
        estado=EstadoJornada.ACTIVA,
    ).exists():
        raise ValidationError({"jornada": "El motorista ya posee una jornada activa."})

    jornada = JornadaRepartidor.objects.create(
        repartidor=repartidor,
        latitud_inicio=datos_validados.get("latitud"),
        longitud_inicio=datos_validados.get("longitud"),
    )

    registrar_operacion_repartidor(
        repartidor,
        usuario,
        estado_nuevo=EstadoOperativoRepartidor.DISPONIBLE,
        motivo="Inicio de jornada.",
    )
    from apps.rutas.models import VersionRuta
    from apps.rutas.servicios import sincronizar_ruta

    sincronizar_ruta(repartidor, VersionRuta.Motivo.INICIO_JORNADA, jornada=jornada)
    from apps.solicitudes.servicios import programar_reintento_pendientes

    programar_reintento_pendientes(repartidor.empresa_id)
    from apps.solicitudes.flujo_automatico import programar_avance_automatico
    programar_avance_automatico(repartidor.pk)
    return jornada


def _calcular_resumen(jornada, finalizada_en):
    from apps.incidencias.models import Incidencia

    kilometros, kilometraje_disponible = calcular_kilometraje_operativo(
        jornada, finalizada_en
    )
    def solicitudes_en_fecha(campo):
        historial = AsignacionSolicitud.objects.filter(solicitud_id=OuterRef("pk"))
        vigente_en_evento = Q(finalizada_en__isnull=True) | Q(finalizada_en__gt=OuterRef(campo))
        if campo == "entregada_en":
            # Entregar cierra la asignación en ese mismo instante; no incluir
            # por igualdad al motorista retirado en una reasignación/cancelación.
            vigente_en_evento |= Q(
                estado=EstadoAsignacionSolicitud.FINALIZADA,
                finalizada_en=OuterRef(campo),
            )
        del_motorista = historial.filter(
            repartidor=jornada.repartidor, asignada_en__lte=OuterRef(campo),
        ).filter(vigente_en_evento)
        return Solicitud.objects.filter(**{
            f"{campo}__gte": jornada.iniciada_en, f"{campo}__lte": finalizada_en,
        }).alias(tiene_historial=Exists(historial), fue_responsable=Exists(del_motorista)).filter(
            Q(fue_responsable=True) | Q(tiene_historial=False, repartidor_asignado=jornada.repartidor),
        )

    solicitudes_entregadas = solicitudes_en_fecha("entregada_en")
    recolecciones = solicitudes_en_fecha("recolectada_en").count()
    entregas = solicitudes_entregadas.count()
    return {
        "kilometros_operativos": kilometros,
        "kilometraje_disponible": kilometraje_disponible,
        "servicios_completados": entregas,
        "recolecciones_completadas": recolecciones,
        "entregas_completadas": entregas,
        "servicios_normales": solicitudes_entregadas.filter(
            prioridad=PrioridadSolicitud.NORMAL
        ).count(),
        "servicios_prioritarios": solicitudes_entregadas.filter(
            prioridad=PrioridadSolicitud.PRIORITARIA
        ).count(),
        "minutos_activos": max(
            0,
            int((finalizada_en - jornada.iniciada_en).total_seconds() // 60),
        ),
        "incidencias_reportadas": Incidencia.objects.filter(
            jornada=jornada,
        ).count(),
    }


def registrar_cierre_jornada(
    jornada,
    repartidor,
    usuario,
    *,
    finalizada_en,
    datos_cierre=None,
    motivo_medicion="CIERRE",
    motivo_estado="Finalización de jornada.",
    finalizada_ruta_en=None,
):
    """Pasos comunes, dentro de la transacción y bloqueos del caso de uso.

    El llamador valida propiedad, permisos, asignaciones y/o vencimiento.
    No decide si procede un cierre manual o automático ni fabrica GPS.
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError(
            "El cierre requiere una transacción y el motorista y jornada bloqueados."
        )
    resumen = _calcular_resumen(jornada, finalizada_en)
    jornada.estado = EstadoJornada.FINALIZADA
    jornada.finalizada_en = finalizada_en
    campos = ["estado", "finalizada_en", *resumen.keys(), "actualizado_en"]
    if datos_cierre is not None:
        jornada.latitud_fin = datos_cierre.get("latitud")
        jornada.longitud_fin = datos_cierre.get("longitud")
        campos += ["latitud_fin", "longitud_fin"]
    for campo, valor in resumen.items():
        setattr(jornada, campo, valor)
    jornada.save(update_fields=campos)

    from apps.seguimiento.sincronizacion import consolidar_jornada

    sesiones_gps = datos_cierre.get("sesiones_gps") if datos_cierre is not None else None
    consolidar_jornada(jornada, sesiones_gps, motivo_medicion)

    registrar_operacion_repartidor(
        repartidor,
        usuario,
        estado_nuevo=EstadoOperativoRepartidor.DESCONECTADO,
        motivo=motivo_estado,
    )
    from apps.rutas.models import VersionRuta
    from apps.rutas.servicios import sincronizar_ruta

    sincronizar_ruta(
        repartidor,
        VersionRuta.Motivo.CIERRE_JORNADA,
        cerrar=True,
        finalizada_en=finalizada_ruta_en,
    )
    return jornada


@transaction.atomic
def finalizar_jornada(usuario, jornada_id, datos_validados):
    _validar_coordenadas(datos_validados)
    repartidor = _obtener_repartidor_propio_bloqueado(usuario)
    try:
        jornada = (
            JornadaRepartidor.objects.select_for_update(of=("self",))
            .select_related("repartidor", "repartidor__empresa")
            .get(id=jornada_id, repartidor__usuario=usuario)
        )
    except (JornadaRepartidor.DoesNotExist, ValueError) as error:
        raise Http404("La jornada activa no existe o no pertenece al motorista.") from error

    _exigir_permiso(usuario, "jornada.finalizar", repartidor)
    if jornada.estado != EstadoJornada.ACTIVA:
        raise ValidationError({"jornada": "La jornada ya está finalizada."})
    if AsignacionSolicitud.objects.filter(
        repartidor=repartidor,
        estado=EstadoAsignacionSolicitud.ACTIVA,
    ).exists():
        raise ValidationError(
            {"jornada": "No puede finalizar mientras tenga asignaciones activas."}
        )
    ahora = timezone.now()
    if settings.MODO_APLICACION == "CORPORATIVO" and repartidor.empresa_id:
        from apps.solicitudes.vigencia import limite_dia_operativo

        corte = limite_dia_operativo(jornada.iniciada_en, repartidor.empresa)
        if ahora >= corte:
            # Un cierre solicitado tarde conserva el corte real del día: las
            # coordenadas actuales del teléfono no describen la medianoche.
            return registrar_cierre_jornada(
                jornada, repartidor, None, finalizada_en=corte,
                motivo_medicion="FIN_DIA", motivo_estado="Fin del día operativo.",
                finalizada_ruta_en=corte,
            )
    return registrar_cierre_jornada(
        jornada,
        repartidor,
        usuario,
        finalizada_en=ahora,
        datos_cierre=datos_validados,
    )


@transaction.atomic
def confirmar_sincronizacion_jornada(usuario, jornada_id, datos_validados):
    repartidor = _obtener_repartidor_propio_bloqueado(usuario)
    _exigir_permiso(usuario, "jornada.finalizar", repartidor)
    try:
        jornada = JornadaRepartidor.objects.select_for_update().get(
            pk=jornada_id, repartidor=repartidor, estado=EstadoJornada.FINALIZADA,
        )
    except JornadaRepartidor.DoesNotExist as error:
        raise Http404("La jornada finalizada no existe o no pertenece al motorista.") from error
    if not jornada.calidad_kilometraje:
        raise ValidationError({"jornada": "Los cierres históricos no se recalculan."})
    if jornada.calidad_kilometraje.get("sincronizacion_verificada"):
        from apps.seguimiento.sincronizacion import normalizar_sesiones

        sesiones = normalizar_sesiones(datos_validados["sesiones_gps"])
        if sesiones != jornada.calidad_kilometraje["sesiones_gps"]:
            raise ValidationError({"sesiones_gps": "El manifiesto del cierre consolidado es inmutable."})
        return jornada
    from apps.seguimiento.sincronizacion import consolidar_jornada

    return consolidar_jornada(jornada, datos_validados["sesiones_gps"], "CONFIRMACION_GPS")
