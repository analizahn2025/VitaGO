"""Consultas autorizadas del dominio de flota."""

from django.db.models import Q
from django.http import Http404
from rest_framework.exceptions import PermissionDenied

from apps.flota.models import Vehiculo
from apps.usuarios.servicios import obtener_alcances_permiso


def _filtro_alcances(alcances):
    if alcances.global_:
        return Q()
    return Q(empresa_id__in=alcances.empresas_visibles)


def listar_vehiculos_autorizados(usuario, filtros=None):
    alcances = obtener_alcances_permiso(usuario, "vehiculo.ver")
    if not alcances.tiene_algun_alcance:
        raise PermissionDenied('No tiene el permiso requerido: "vehiculo.ver".')

    consulta = Vehiculo.objects.select_related("empresa").filter(
        _filtro_alcances(alcances)
    )
    filtros = filtros or {}
    if filtros.get("empresa_id"):
        consulta = consulta.filter(empresa_id=filtros["empresa_id"])
    if filtros.get("estado"):
        consulta = consulta.filter(estado=filtros["estado"])
    if filtros.get("tipo"):
        consulta = consulta.filter(tipo=filtros["tipo"])
    return consulta.order_by("placa", "id")


def obtener_vehiculo_autorizado(usuario, identificador_vehiculo):
    try:
        return listar_vehiculos_autorizados(usuario).get(
            id=identificador_vehiculo
        )
    except (Vehiculo.DoesNotExist, ValueError) as error:
        raise Http404(
            "El vehículo no existe o no está dentro de su alcance."
        ) from error
