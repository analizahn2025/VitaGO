"""Casos de uso transaccionales para jornadas de motoristas."""

from django.db import transaction
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.flota.opciones import EstadoVehiculo, TipoVehiculo
from apps.jornadas.models import JornadaRepartidor
from apps.jornadas.kilometraje import calcular_kilometraje_operativo
from apps.jornadas.opciones import EstadoJornada
from apps.repartidores.models import HistorialEstadoRepartidor, Repartidor
from apps.repartidores.capacidad import calcular_capacidad, contar_solicitudes_activas
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


def _registrar_estado_repartidor(
    repartidor,
    usuario,
    *,
    estado_nuevo,
    motivo,
):
    estado_anterior = repartidor.estado_operativo
    capacidad_anterior = repartidor.capacidad
    capacidad_nueva = calcular_capacidad(contar_solicitudes_activas(repartidor))
    if estado_anterior == estado_nuevo and capacidad_anterior == capacidad_nueva:
        return

    repartidor.estado_operativo = estado_nuevo
    repartidor.capacidad = capacidad_nueva
    repartidor.save(
        update_fields=("estado_operativo", "capacidad", "actualizado_en")
    )
    HistorialEstadoRepartidor.objects.create(
        repartidor=repartidor,
        estado_anterior=estado_anterior,
        estado_nuevo=estado_nuevo,
        capacidad_anterior=capacidad_anterior,
        capacidad_nueva=capacidad_nueva,
        realizado_por=usuario,
        motivo=motivo,
    )


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

    _registrar_estado_repartidor(
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
    return jornada


def _calcular_resumen(jornada, finalizada_en):
    from apps.incidencias.models import Incidencia

    kilometros, kilometraje_disponible = calcular_kilometraje_operativo(
        jornada, finalizada_en
    )
    solicitudes_entregadas = Solicitud.objects.filter(
        repartidor_asignado=jornada.repartidor,
        entregada_en__gte=jornada.iniciada_en,
        entregada_en__lte=finalizada_en,
    )
    recolecciones = Solicitud.objects.filter(
        repartidor_asignado=jornada.repartidor,
        recolectada_en__gte=jornada.iniciada_en,
        recolectada_en__lte=finalizada_en,
    ).count()
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
    resumen = _calcular_resumen(jornada, ahora)
    jornada.estado = EstadoJornada.FINALIZADA
    jornada.finalizada_en = ahora
    jornada.latitud_fin = datos_validados.get("latitud")
    jornada.longitud_fin = datos_validados.get("longitud")
    for campo, valor in resumen.items():
        setattr(jornada, campo, valor)
    jornada.save(
        update_fields=(
            "estado",
            "finalizada_en",
            "latitud_fin",
            "longitud_fin",
            *resumen.keys(),
            "actualizado_en",
        )
    )

    from apps.seguimiento.sincronizacion import consolidar_jornada

    consolidar_jornada(jornada, datos_validados.get("sesiones_gps"))

    _registrar_estado_repartidor(
        repartidor,
        usuario,
        estado_nuevo=EstadoOperativoRepartidor.DESCONECTADO,
        motivo="Finalización de jornada.",
    )
    from apps.rutas.models import VersionRuta
    from apps.rutas.servicios import sincronizar_ruta

    sincronizar_ruta(repartidor, VersionRuta.Motivo.CIERRE_JORNADA, cerrar=True)
    return jornada


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
