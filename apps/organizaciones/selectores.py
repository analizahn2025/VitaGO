"""Consultas de organizaciones restringidas por permisos y alcance."""

from django.db.models import Q
from django.http import Http404
from rest_framework.exceptions import PermissionDenied

from apps.organizaciones.models import Empresa, Sucursal
from apps.usuarios.servicios import obtener_alcances_permiso


def _exigir_algun_alcance(alcances, codigo_permiso):
    if not alcances.tiene_algun_alcance:
        raise PermissionDenied(
            f'No tiene el permiso requerido: "{codigo_permiso}".'
        )


def _consulta_empresas_segun_alcance(alcances):
    consulta = Empresa.objects.select_related("pais").order_by("nombre", "id")
    if alcances.global_:
        return consulta
    return consulta.filter(id__in=alcances.empresas_visibles)


def listar_empresas_autorizadas(usuario):
    alcances = obtener_alcances_permiso(usuario, "empresa.ver")
    _exigir_algun_alcance(alcances, "empresa.ver")
    return _consulta_empresas_segun_alcance(alcances)


def obtener_empresa_autorizada(usuario, identificador_empresa):
    alcances = obtener_alcances_permiso(usuario, "empresa.ver")
    _exigir_algun_alcance(alcances, "empresa.ver")
    try:
        return _consulta_empresas_segun_alcance(alcances).get(
            id=identificador_empresa
        )
    except (Empresa.DoesNotExist, ValueError) as error:
        raise Http404(
            "La empresa no existe o no está dentro de su alcance."
        ) from error


def _consulta_sucursales_segun_alcance(alcances):
    consulta = Sucursal.objects.select_related(
        "empresa",
        "ubicacion",
        "ubicacion__tipo_ubicacion",
        "ubicacion__pais",
    ).order_by("nombre", "id")
    if alcances.global_:
        return consulta
    return consulta.filter(
        Q(empresa_id__in=alcances.empresas)
        | Q(id__in=alcances.sucursales)
    )


def listar_sucursales_autorizadas(usuario, identificador_empresa):
    alcances = obtener_alcances_permiso(usuario, "sucursal.ver")
    _exigir_algun_alcance(alcances, "sucursal.ver")
    if not alcances.permite_empresa(identificador_empresa):
        raise Http404(
            "La empresa no existe o no está dentro de su alcance."
        )

    try:
        empresa = Empresa.objects.select_related("pais").get(
            id=identificador_empresa
        )
    except (Empresa.DoesNotExist, ValueError) as error:
        raise Http404(
            "La empresa no existe o no está dentro de su alcance."
        ) from error

    consulta = _consulta_sucursales_segun_alcance(alcances).filter(
        empresa_id=empresa.id
    )
    return empresa, consulta


def obtener_sucursal_autorizada(usuario, identificador_sucursal):
    alcances = obtener_alcances_permiso(usuario, "sucursal.ver")
    _exigir_algun_alcance(alcances, "sucursal.ver")
    try:
        return _consulta_sucursales_segun_alcance(alcances).get(
            id=identificador_sucursal
        )
    except (Sucursal.DoesNotExist, ValueError) as error:
        raise Http404(
            "La sucursal no existe o no está dentro de su alcance."
        ) from error
