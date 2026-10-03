"""Consultas autorizadas y optimizadas de motoristas."""

from django.db.models import Q
from django.http import Http404
from rest_framework.exceptions import PermissionDenied

from apps.repartidores.capacidad import (
    LIMITE_SOLICITUDES,
    anotar_carga_repartidores,
    filtrar_repartidores_disponibles,
)
from apps.repartidores.models import Repartidor
from apps.repartidores.opciones import (
    CapacidadRepartidor,
    EstadoOperativoRepartidor,
)
from apps.usuarios.servicios import obtener_alcances_permiso


def _filtro_alcances(alcances):
    if alcances.global_:
        return Q()
    return Q(empresa_id__in=alcances.empresas_visibles)


def _consulta_base():
    return anotar_carga_repartidores(
        Repartidor.objects.select_related("usuario", "empresa", "vehiculo")
    )


def listar_repartidores_autorizados(usuario, filtros=None):
    alcances = obtener_alcances_permiso(usuario, "repartidor.ver")
    if not alcances.tiene_algun_alcance:
        raise PermissionDenied('No tiene el permiso requerido: "repartidor.ver".')

    consulta = _consulta_base().filter(_filtro_alcances(alcances))
    filtros = filtros or {}
    if filtros.get("empresa_id"):
        consulta = consulta.filter(empresa_id=filtros["empresa_id"])
    if filtros.get("estado_operativo"):
        consulta = consulta.filter(estado_operativo=filtros["estado_operativo"])
    if filtros.get("capacidad"):
        if filtros["capacidad"] == CapacidadRepartidor.VACIO:
            consulta = consulta.filter(solicitudes_activas_calculadas=0)
        elif filtros["capacidad"] == CapacidadRepartidor.LLENO:
            consulta = consulta.filter(
                solicitudes_activas_calculadas__gte=LIMITE_SOLICITUDES
            )
        else:
            consulta = consulta.filter(
                solicitudes_activas_calculadas__gt=0,
                solicitudes_activas_calculadas__lt=LIMITE_SOLICITUDES,
            )
    if "activo" in filtros:
        consulta = consulta.filter(activo=filtros["activo"])
    return consulta.order_by("usuario__nombres", "usuario__apellidos", "id")


def listar_repartidores_disponibles(usuario, filtros=None):
    return filtrar_repartidores_disponibles(
        listar_repartidores_autorizados(usuario, filtros)
    )


def obtener_repartidor_autorizado(usuario, identificador_repartidor):
    try:
        return listar_repartidores_autorizados(usuario).get(
            id=identificador_repartidor
        )
    except (Repartidor.DoesNotExist, ValueError) as error:
        raise Http404(
            "El motorista no existe o no está dentro de su alcance."
        ) from error


def obtener_repartidor_propio(usuario):
    """Consulta únicamente el perfil operativo activo del usuario autenticado."""
    try:
        return _consulta_base().get(usuario_id=usuario.pk, activo=True)
    except Repartidor.DoesNotExist as error:
        raise Http404("El usuario no posee un perfil activo de motorista.") from error
