"""Consultas autorizadas de jornadas de motoristas."""

from django.db.models import Q
from django.http import Http404
from rest_framework.exceptions import PermissionDenied

from apps.jornadas.models import JornadaRepartidor
from apps.jornadas.opciones import EstadoJornada
from apps.repartidores.models import Repartidor
from apps.usuarios.servicios import obtener_alcances_permiso


def _consulta_base():
    return JornadaRepartidor.objects.select_related(
        "repartidor",
        "repartidor__usuario",
        "repartidor__empresa",
        "repartidor__vehiculo",
    )


def _obtener_repartidor_propio(usuario):
    try:
        return Repartidor.objects.select_related(
            "usuario",
            "empresa",
            "vehiculo",
        ).get(usuario=usuario, activo=True)
    except Repartidor.DoesNotExist as error:
        raise Http404("El usuario no posee un perfil activo de motorista.") from error


def listar_jornadas_autorizadas(usuario, filtros=None):
    alcances = obtener_alcances_permiso(usuario, "jornada.ver")
    if not alcances.tiene_algun_alcance:
        raise PermissionDenied(
            'No tiene el permiso requerido: "jornada.ver".'
        )

    alcances_administracion = obtener_alcances_permiso(
        usuario,
        "repartidor.administrar",
    )
    consulta = _consulta_base()
    if alcances_administracion.tiene_algun_alcance:
        if not alcances_administracion.global_:
            consulta = consulta.filter(
                repartidor__empresa_id__in=(
                    alcances_administracion.empresas_visibles
                )
            )
    else:
        repartidor = _obtener_repartidor_propio(usuario)
        consulta = consulta.filter(repartidor=repartidor)

    filtros = filtros or {}
    if filtros.get("repartidor_id"):
        consulta = consulta.filter(repartidor_id=filtros["repartidor_id"])
    if filtros.get("estado"):
        consulta = consulta.filter(estado=filtros["estado"])
    if filtros.get("desde"):
        consulta = consulta.filter(iniciada_en__gte=filtros["desde"])
    if filtros.get("hasta"):
        consulta = consulta.filter(iniciada_en__lte=filtros["hasta"])
    return consulta.order_by("-iniciada_en", "-id")


def obtener_jornada_autorizada(usuario, jornada_id):
    try:
        return listar_jornadas_autorizadas(usuario).get(id=jornada_id)
    except (JornadaRepartidor.DoesNotExist, ValueError) as error:
        raise Http404(
            "La jornada no existe o no está dentro de su alcance."
        ) from error


def obtener_jornada_activa_propia(usuario):
    alcances = obtener_alcances_permiso(usuario, "jornada.ver")
    if not alcances.tiene_algun_alcance:
        raise PermissionDenied(
            'No tiene el permiso requerido: "jornada.ver".'
        )
    repartidor = _obtener_repartidor_propio(usuario)
    return (
        _consulta_base()
        .filter(repartidor=repartidor, estado=EstadoJornada.ACTIVA)
        .first()
    )

