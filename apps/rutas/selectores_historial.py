"""Consultas autorizadas del historial inmutable de rutas."""

from django.db.models import Count, Exists, OuterRef, Q
from django.http import Http404
from rest_framework.exceptions import PermissionDenied

from apps.rutas.models import ParadaVersionRuta, RutaRepartidor, VersionRuta
from apps.usuarios.servicios import obtener_alcances_permiso


def _empresas_administrables(alcances_rutas, alcances_ubicacion):
    """Devuelve None solo si ambos permisos tienen alcance global."""
    if alcances_rutas.global_ and alcances_ubicacion.global_:
        return None
    if alcances_rutas.global_:
        return alcances_ubicacion.empresas
    if alcances_ubicacion.global_:
        return alcances_rutas.empresas
    return alcances_rutas.empresas & alcances_ubicacion.empresas


def listar_rutas_autorizadas(usuario, filtros=None):
    alcances_rutas = obtener_alcances_permiso(usuario, "ruta.ver")
    if not alcances_rutas.tiene_algun_alcance:
        raise PermissionDenied('No tiene el permiso requerido: "ruta.ver".')

    propias = RutaRepartidor.objects.none()
    if alcances_rutas.global_:
        propias = RutaRepartidor.objects.filter(repartidor__usuario_id=usuario.pk)
    elif alcances_rutas.empresas:
        propias = RutaRepartidor.objects.filter(
            repartidor__usuario_id=usuario.pk,
            repartidor__empresa_id__in=alcances_rutas.empresas,
        )

    alcances_ubicacion = obtener_alcances_permiso(
        usuario, "repartidor.ver_ubicacion"
    )
    administrables = RutaRepartidor.objects.none()
    if alcances_ubicacion.tiene_algun_alcance:
        empresas = _empresas_administrables(alcances_rutas, alcances_ubicacion)
        if empresas is None:
            administrables = RutaRepartidor.objects.all()
        elif empresas:
            paradas_ajenas = ParadaVersionRuta.objects.filter(
                version__ruta_id=OuterRef("pk")
            ).exclude(solicitud__empresa_id__in=empresas)
            administrables = (
                RutaRepartidor.objects.filter(repartidor__empresa_id__in=empresas)
                .alias(tiene_paradas_ajenas=Exists(paradas_ajenas))
                .filter(tiene_paradas_ajenas=False)
            )

    consulta = (
        RutaRepartidor.objects.filter(
            Q(pk__in=propias.values("pk"))
            | Q(pk__in=administrables.values("pk"))
        )
        .select_related("repartidor", "jornada")
        .annotate(cantidad_versiones=Count("versiones", distinct=True))
    )
    filtros = filtros or {}
    if filtros.get("repartidor_id"):
        consulta = consulta.filter(repartidor_id=filtros["repartidor_id"])
    if filtros.get("estado"):
        consulta = consulta.filter(estado=filtros["estado"])
    return consulta.order_by("-iniciada_en", "-id")


def obtener_ruta_autorizada(usuario, ruta_id):
    try:
        return listar_rutas_autorizadas(usuario).get(id=ruta_id)
    except (RutaRepartidor.DoesNotExist, ValueError) as error:
        raise Http404("La ruta no existe o no está dentro de su alcance.") from error


def listar_versiones_autorizadas(usuario, ruta_id):
    ruta = obtener_ruta_autorizada(usuario, ruta_id)
    return (
        VersionRuta.objects.filter(ruta=ruta)
        .annotate(cantidad_paradas=Count("paradas"))
        .order_by("-numero")
    )


def obtener_version_autorizada(usuario, ruta_id, numero):
    try:
        return (
            listar_versiones_autorizadas(usuario, ruta_id)
            .prefetch_related("paradas")
            .get(numero=numero)
        )
    except VersionRuta.DoesNotExist as error:
        raise Http404("La versión de ruta no existe.") from error
