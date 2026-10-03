"""Casos de uso para registrar ubicaciones enviadas por los dispositivos."""

from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.jornadas.models import JornadaRepartidor
from apps.repartidores.models import Repartidor
from apps.seguimiento.models import RegistroUbicacion
from apps.solicitudes.models import AsignacionSolicitud
from apps.solicitudes.servicios_movimientos import (
    movimiento_correspondiente,
    obtener_movimientos_para_registros,
)
from apps.usuarios.opciones import EstadoUsuario
from apps.usuarios.servicios import usuario_tiene_permiso


def _obtener_repartidor_propio(usuario):
    try:
        return Repartidor.objects.select_related("empresa").get(
            usuario=usuario, activo=True, usuario__estado=EstadoUsuario.ACTIVO,
        )
    except Repartidor.DoesNotExist as error:
        raise Http404("El usuario no posee un perfil activo de motorista.") from error


def _obtener_jornada_propia(repartidor, jornada_id):
    try:
        return JornadaRepartidor.objects.get(id=jornada_id, repartidor=repartidor)
    except (JornadaRepartidor.DoesNotExist, ValueError) as error:
        raise Http404("La jornada no existe o no pertenece al motorista.") from error


def _validar_intervalo_jornada(jornada, registros, ahora):
    limite_superior = jornada.finalizada_en or ahora
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
    )
    return existente.jornada_id == jornada.id and all(
        getattr(existente, campo) == datos.get(campo) for campo in campos
    )


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
    _validar_intervalo_jornada(jornada, registros, timezone.now())

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

    guardados = {
        registro.id_cliente: registro
        for registro in RegistroUbicacion.objects.filter(
            repartidor=repartidor, id_cliente__in=identificadores,
        )
    }
    return {
        "recibidos": len(registros),
        "creados": len(nuevos),
        "repetidos": len(registros) - len(nuevos),
        "registros": [
            guardados[identificador] for identificador in identificadores
        ],
    }
