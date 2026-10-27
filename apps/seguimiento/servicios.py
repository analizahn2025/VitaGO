"""Casos de uso para registrar ubicaciones enviadas por los dispositivos."""

from django.db import transaction
from django.conf import settings
from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.jornadas.models import JornadaRepartidor
from apps.repartidores.models import Repartidor
from apps.seguimiento.models import RegistroUbicacion
from apps.solicitudes.models import AsignacionSolicitud, MovimientoEnvioEspecial
from apps.solicitudes.opciones import EstadoMovimientoEnvioEspecial
from apps.solicitudes.servicios_movimientos import (
    movimiento_correspondiente,
    obtener_movimientos_para_registros,
)
from apps.usuarios.opciones import EstadoUsuario
from apps.usuarios.servicios import usuario_tiene_permiso


def _obtener_repartidor_propio(usuario):
    try:
        return Repartidor.objects.select_for_update(of=("self",)).select_related("empresa").get(
            usuario=usuario, activo=True, usuario__estado=EstadoUsuario.ACTIVO,
        )
    except Repartidor.DoesNotExist as error:
        raise Http404("El usuario no posee un perfil activo de motorista.") from error


def _obtener_jornada_propia(repartidor, jornada_id):
    try:
        return JornadaRepartidor.objects.select_for_update().get(id=jornada_id, repartidor=repartidor)
    except (JornadaRepartidor.DoesNotExist, ValueError) as error:
        raise Http404("La jornada no existe o no pertenece al motorista.") from error


def _validar_intervalo_jornada(jornada, registros, ahora):
    limite_superior = min(jornada.finalizada_en or ahora, ahora)
    errores = {}
    for indice, registro in enumerate(registros):
        if not jornada.iniciada_en <= registro["registrada_en"] <= limite_superior:
            errores[indice] = {
                "registrada_en": (
                    "Debe pertenecer al intervalo de la jornada indicada."
                )
            }
    if errores:
        raise ValidationError({"registros": errores})


def _intervalos_operativos(repartidor, registros):
    desde = min(registro["registrada_en"] for registro in registros)
    hasta = max(registro["registrada_en"] for registro in registros)
    return list(
        AsignacionSolicitud.objects.filter(
            repartidor=repartidor, aceptada_en__isnull=False, aceptada_en__lte=hasta,
        )
        .filter(Q(finalizada_en__isnull=True) | Q(finalizada_en__gte=desde))
        .values_list("aceptada_en", "finalizada_en")
    )


def _es_instante_operativo(registrada_en, intervalos):
    return any(
        inicio <= registrada_en and (fin is None or registrada_en <= fin)
        for inicio, fin in intervalos
    )


def _coincide_registro_existente(existente, jornada, datos):
    campos = (
        "latitud", "longitud", "precision_metros", "velocidad_metros_segundo",
        "rumbo_grados", "registrada_en",
        "sesion_gps", "secuencia",
    )
    return existente.jornada_id == jornada.id and all(
        getattr(existente, campo) == datos.get(campo) for campo in campos
    )


def _validar_prefijos_especiales_verificados(jornada, registros, existentes):
    # El manifiesto del especial confirma TODO el prefijo de la jornada,
    # incluidos los puntos anteriores al inicio de ese movimiento.
    # El motorista ya está bloqueado, igual que al confirmar un especial.
    limite_verificado = (
        MovimientoEnvioEspecial.objects.filter(
            jornada=jornada,
            estado=EstadoMovimientoEnvioEspecial.FINALIZADO,
            calidad_kilometraje__sincronizacion_verificada=True,
        )
        .order_by("-finalizada_en")
        .values_list("finalizada_en", flat=True)
        .first()
    )
    if limite_verificado is None:
        return
    errores = {
        indice: {
            "registrada_en": (
                "La fecha pertenece al prefijo GPS de un envío especial ya "
                "consolidado; solo admite reintentos idénticos."
            )
        }
        for indice, datos in enumerate(registros)
        if datos["id_cliente"] not in existentes
        and datos["registrada_en"] <= limite_verificado
    }
    if errores:
        raise ValidationError({"registros": errores})


@transaction.atomic
def registrar_ubicaciones(usuario, datos_validados):
    repartidor = _obtener_repartidor_propio(usuario)
    if not usuario_tiene_permiso(
        usuario, "repartidor.registrar_ubicacion", empresa=repartidor.empresa,
    ):
        raise PermissionDenied(
            'No tiene el permiso requerido: '
            '"repartidor.registrar_ubicacion".'
        )

    jornada = _obtener_jornada_propia(repartidor, datos_validados["jornada_id"])
    registros = datos_validados["registros"]
    limite = timezone.now()
    if settings.MODO_APLICACION == "CORPORATIVO" and repartidor.empresa_id:
        from apps.solicitudes.vigencia import limite_dia_operativo
        limite = min(limite, limite_dia_operativo(jornada.iniciada_en, repartidor.empresa))
    _validar_intervalo_jornada(jornada, registros, limite)

    identificadores = [registro["id_cliente"] for registro in registros]
    existentes = {
        registro.id_cliente: registro
        for registro in RegistroUbicacion.objects.filter(
            repartidor=repartidor, id_cliente__in=identificadores,
        )
    }
    conflictos = [
        str(datos["id_cliente"])
        for datos in registros
        if datos["id_cliente"] in existentes
        and not _coincide_registro_existente(
            existentes[datos["id_cliente"]],
            jornada,
            datos,
        )
    ]
    if conflictos:
        raise ValidationError(
            {
                "registros": (
                    "Los siguientes id_cliente ya existen con otros datos: "
                    + ", ".join(conflictos)
                )
            }
        )

    nuevos_datos = [
        datos for datos in registros if datos["id_cliente"] not in existentes
    ]
    sesiones = {datos["sesion_gps"] for datos in nuevos_datos if datos.get("sesion_gps")}
    if sesiones and RegistroUbicacion.objects.filter(
        repartidor=repartidor, sesion_gps__in=sesiones,
    ).exclude(jornada=jornada).exists():
        raise ValidationError({"registros": "Una sesión GPS no puede reutilizarse en otra jornada."})
    condicion = Q(pk__in=[])
    for sesion in sesiones:
        secuencias = [d["secuencia"] for d in nuevos_datos if d.get("sesion_gps") == sesion]
        condicion |= Q(sesion_gps=sesion, secuencia__in=secuencias)
    existentes_secuencia = set(RegistroUbicacion.objects.filter(
        condicion, repartidor=repartidor,
    ).values_list("sesion_gps", "secuencia")) if sesiones else set()
    errores = {
        indice: {"secuencia": "Ya existe esta secuencia GPS con otro id_cliente."}
        for indice, datos in enumerate(registros)
        if datos in nuevos_datos and (datos.get("sesion_gps"), datos.get("secuencia")) in existentes_secuencia
    }
    if errores:
        raise ValidationError({"registros": errores})
    # Tras verificar un cierre no se admiten puntos nuevos que contradigan el manifiesto.
    if jornada.calidad_kilometraje.get("sincronizacion_verificada") and nuevos_datos:
        raise ValidationError({"registros": "La medición de esta jornada ya fue consolidada; solo admite reintentos idénticos."})
    if nuevos_datos:
        _validar_prefijos_especiales_verificados(jornada, registros, existentes)
    intervalos = (
        _intervalos_operativos(repartidor, nuevos_datos)
        if nuevos_datos
        else []
    )
    movimientos_especiales = obtener_movimientos_para_registros(
        repartidor,
        nuevos_datos,
    )
    nuevos = [
        RegistroUbicacion(
            repartidor=repartidor,
            jornada=jornada,
            es_operativo=_es_instante_operativo(datos["registrada_en"], intervalos),
            movimiento_envio_especial=movimiento_correspondiente(
                datos["registrada_en"],
                jornada.id,
                movimientos_especiales,
            ),
            **datos,
        )
        for datos in nuevos_datos
    ]
    RegistroUbicacion.objects.bulk_create(nuevos, ignore_conflicts=True)
    if nuevos:
        from apps.seguimiento.sincronizacion import revisar_mediciones_pendientes
        from apps.seguimiento.vigencia import posiciones_vigentes
        from apps.solicitudes.servicios import programar_reintento_pendientes

        revisar_mediciones_pendientes(jornada)
        if posiciones_vigentes().filter(repartidor=repartidor).exists():
            programar_reintento_pendientes(repartidor.empresa_id)

    guardados = {
        registro.id_cliente: registro
        for registro in RegistroUbicacion.objects.filter(
            repartidor=repartidor, id_cliente__in=identificadores,
        )
    }
    resultado = {
        "recibidos": len(registros),
        "creados": len(nuevos),
        "repetidos": len(registros) - len(nuevos),
        "registros": [
            guardados[identificador] for identificador in identificadores
        ],
        "llegadas_detectadas": [],
    }
    # También se evalúan reintentos idénticos: permiten recuperar una detección
    # que falló transitoriamente sin duplicar puntos ni eventos. Nunca se
    # bloquea una solicitud mientras se mantiene el bloqueo de recepción GPS.
    from apps.seguimiento.llegadas import programar_deteccion_llegada
    from apps.solicitudes.flujo_automatico import programar_avance_automatico
    programar_avance_automatico(repartidor.pk)
    programar_deteccion_llegada(usuario, repartidor.id, jornada.id, resultado)
    return resultado
