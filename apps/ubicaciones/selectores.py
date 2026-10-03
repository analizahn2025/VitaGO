"""Consultas autorizadas de catálogos y ubicaciones."""

from django.http import Http404
from rest_framework.exceptions import PermissionDenied

from apps.organizaciones.models import Empresa
from apps.ubicaciones.models import TipoUbicacion, Ubicacion, UbicacionEmpresa
from apps.usuarios.servicios import obtener_alcances_permiso


def _exigir_algun_alcance(alcances, codigo_permiso):
    if not alcances.tiene_algun_alcance:
        raise PermissionDenied(
            f'No tiene el permiso requerido: "{codigo_permiso}".'
        )


def listar_tipos_ubicacion_autorizados(usuario):
    alcances = obtener_alcances_permiso(usuario, "ubicacion.ver")
    _exigir_algun_alcance(alcances, "ubicacion.ver")
    return TipoUbicacion.objects.filter(activo=True).order_by("nombre", "id")


def listar_ubicaciones_autorizadas(usuario, identificador_empresa):
    """Lista las ubicaciones habilitadas para una empresa visible."""
    alcances = obtener_alcances_permiso(usuario, "ubicacion.ver")
    _exigir_algun_alcance(alcances, "ubicacion.ver")
    if not alcances.permite_empresa(identificador_empresa):
        raise Http404(
            "La empresa no existe o no está dentro de su alcance."
        )

    try:
        empresa = Empresa.objects.get(id=identificador_empresa)
    except (Empresa.DoesNotExist, ValueError) as error:
        raise Http404(
            "La empresa no existe o no está dentro de su alcance."
        ) from error

    relaciones = (
        UbicacionEmpresa.objects.filter(empresa_id=empresa.id)
        .select_related(
            "empresa",
            "ubicacion",
            "ubicacion__tipo_ubicacion",
            "ubicacion__pais",
        )
        .order_by("ubicacion__nombre", "ubicacion_id")
    )
    return empresa, relaciones


def obtener_ubicacion_autorizada(usuario, identificador_ubicacion):
    """Obtiene una ubicación sin revelar recursos fuera del alcance."""
    alcances = obtener_alcances_permiso(usuario, "ubicacion.ver")
    _exigir_algun_alcance(alcances, "ubicacion.ver")

    consulta = Ubicacion.objects.select_related(
        "tipo_ubicacion",
        "pais",
    )
    if not alcances.global_:
        consulta = consulta.filter(
            empresas_autorizadas__empresa_id__in=alcances.empresas_visibles
        ).distinct()

    try:
        return consulta.get(id=identificador_ubicacion)
    except (Ubicacion.DoesNotExist, ValueError) as error:
        raise Http404(
            "La ubicación no existe o no está dentro de su alcance."
        ) from error
