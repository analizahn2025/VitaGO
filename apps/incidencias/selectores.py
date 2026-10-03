"""Consultas autorizadas del dominio de incidencias."""

from django.db.models import Q
from django.http import Http404
from rest_framework.exceptions import PermissionDenied

from apps.incidencias.models import EvidenciaIncidencia, Incidencia
from apps.usuarios.servicios import obtener_alcances_permiso


def _consulta_base():
    return Incidencia.objects.select_related(
        "jornada",
        "repartidor",
        "repartidor__usuario",
        "repartidor__empresa",
        "solicitud",
        "revisada_por",
    ).prefetch_related("eventos")


def listar_incidencias_autorizadas(usuario, filtros=None):
    alcances_creacion = obtener_alcances_permiso(usuario, "incidencia.crear")
    alcances_revision = obtener_alcances_permiso(usuario, "incidencia.revisar")
    if not (
        alcances_creacion.tiene_algun_alcance
        or alcances_revision.tiene_algun_alcance
    ):
        raise PermissionDenied(
            "No tiene permisos para consultar incidencias."
        )

    if alcances_revision.global_:
        filtro_visibilidad = Q()
    else:
        filtro_visibilidad = Q(pk__isnull=True)
        if alcances_creacion.tiene_algun_alcance:
            filtro_visibilidad |= Q(repartidor__usuario_id=usuario.pk)
        if alcances_revision.tiene_algun_alcance:
            filtro_visibilidad |= Q(
                repartidor__empresa_id__in=(
                    alcances_revision.empresas_visibles
                )
            )

    consulta = _consulta_base().filter(filtro_visibilidad).distinct()
    filtros = filtros or {}
    if filtros.get("estado"):
        consulta = consulta.filter(estado=filtros["estado"])
    if filtros.get("jornada_id"):
        consulta = consulta.filter(jornada_id=filtros["jornada_id"])
    if filtros.get("solicitud_id"):
        consulta = consulta.filter(solicitud_id=filtros["solicitud_id"])
    if filtros.get("repartidor_id"):
        consulta = consulta.filter(repartidor_id=filtros["repartidor_id"])
    return consulta.order_by("-reportada_en", "-id")


def obtener_incidencia_autorizada(usuario, incidencia_id):
    try:
        return listar_incidencias_autorizadas(usuario).get(id=incidencia_id)
    except (Incidencia.DoesNotExist, ValueError) as error:
        raise Http404(
            "La incidencia no existe o no está dentro de su alcance."
        ) from error


def listar_evidencias_incidencia_autorizadas(usuario, incidencia_id):
    incidencia = obtener_incidencia_autorizada(usuario, incidencia_id)
    return EvidenciaIncidencia.objects.filter(
        incidencia=incidencia
    ).select_related("repartidor", "repartidor__usuario")


def obtener_evidencia_incidencia_autorizada(
    usuario,
    incidencia_id,
    evidencia_id,
):
    incidencia = obtener_incidencia_autorizada(usuario, incidencia_id)
    try:
        return EvidenciaIncidencia.objects.select_related(
            "incidencia",
            "repartidor",
        ).get(id=evidencia_id, incidencia=incidencia)
    except (EvidenciaIncidencia.DoesNotExist, ValueError) as error:
        raise Http404(
            "La evidencia no existe o no está dentro de su alcance."
        ) from error
