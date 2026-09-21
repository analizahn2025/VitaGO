"""Consultas de autorización basadas en permisos y alcance."""

from django.db.models import Q

from apps.usuarios.models import RolUsuario
from apps.usuarios.opciones import TipoAlcanceRol


def _obtener_identificador(valor):
    if valor is None:
        return None
    return getattr(valor, "pk", valor)


def usuario_tiene_permiso(
    usuario,
    codigo_permiso,
    *,
    empresa=None,
    sucursal=None,
):
    """Indica si un usuario activo posee un permiso en el alcance solicitado."""
    if not usuario or not getattr(usuario, "is_authenticated", False):
        return False
    if not usuario.is_active:
        return False

    codigo_normalizado = codigo_permiso.strip().casefold()
    id_empresa = _obtener_identificador(empresa)
    id_sucursal = _obtener_identificador(sucursal)
    id_empresa_sucursal = getattr(sucursal, "empresa_id", None)

    if sucursal is not None and empresa is not None:
        if id_empresa_sucursal is None or id_empresa_sucursal != id_empresa:
            return False

    if id_empresa is None and sucursal is not None:
        id_empresa = id_empresa_sucursal

    filtro_alcance = Q(tipo_alcance=TipoAlcanceRol.GLOBAL)
    if id_empresa is not None:
        filtro_alcance |= Q(
            tipo_alcance=TipoAlcanceRol.EMPRESA,
            empresa_id=id_empresa,
        )
    if id_sucursal is not None:
        filtro_alcance |= Q(
            tipo_alcance=TipoAlcanceRol.SUCURSAL,
            sucursal_id=id_sucursal,
        )

    return (
        RolUsuario.objetos.filter(
            usuario_id=usuario.pk,
            activo=True,
            rol__activo=True,
            rol__asignaciones_permisos__activo=True,
            rol__asignaciones_permisos__permiso__activo=True,
            rol__asignaciones_permisos__permiso__codigo=codigo_normalizado,
        )
        .filter(filtro_alcance)
        .exists()
    )
