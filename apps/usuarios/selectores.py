"""Consultas optimizadas de lectura para usuarios."""

from django.db.models import Prefetch, Q
from django.http import Http404
from rest_framework.exceptions import PermissionDenied

from apps.usuarios.models import Permiso, RolUsuario, Usuario
from apps.usuarios.opciones import TipoAlcanceRol
from apps.usuarios.servicios.permisos import obtener_alcances_permiso


def _resumen_organizacion(organizacion):
    if organizacion is None:
        return None
    return {
        "id": organizacion.id,
        "nombre": organizacion.nombre,
    }


def obtener_perfil_usuario(usuario):
    """Obtiene identidad, contexto organizacional y autorizaciones vigentes."""
    asignaciones = list(
        RolUsuario.objetos.filter(
            usuario_id=usuario.pk,
            activo=True,
            rol__activo=True,
        )
        .select_related("rol", "empresa", "sucursal")
        .order_by(
            "rol__codigo",
            "tipo_alcance",
            "empresa_id",
            "sucursal_id",
        )
    )

    identificadores_roles = {asignacion.rol_id for asignacion in asignaciones}
    if usuario.es_superusuario:
        consulta_permisos = Permiso.objetos.filter(activo=True)
    elif identificadores_roles:
        consulta_permisos = Permiso.objetos.filter(
            activo=True,
            asignaciones_roles__activo=True,
            asignaciones_roles__rol_id__in=identificadores_roles,
        )
    else:
        consulta_permisos = None

    permisos = []
    if consulta_permisos is not None:
        permisos = sorted(
            set(
                consulta_permisos.distinct()
                .order_by("codigo")
                .values_list("codigo", flat=True)
            )
        )

    return {
        "usuario": {
            "id": usuario.id,
            "correo": usuario.correo,
            "nombres": usuario.nombres,
            "apellidos": usuario.apellidos,
            "telefono": usuario.telefono,
            "estado": usuario.estado,
        },
        "empresa": _resumen_organizacion(usuario.empresa),
        "sucursal": _resumen_organizacion(usuario.sucursal),
        "roles": [
            {
                "codigo": asignacion.rol.codigo,
                "nombre": asignacion.rol.nombre,
                "tipo_alcance": asignacion.tipo_alcance,
                "empresa_id": asignacion.empresa_id,
                "sucursal_id": asignacion.sucursal_id,
            }
            for asignacion in asignaciones
        ],
        "permisos": permisos,
    }


def listar_usuarios_autorizados(usuario):
    """Lista usuarios visibles mediante el permiso y alcance vigentes."""
    alcances = obtener_alcances_permiso(usuario, "usuario.ver")
    if not alcances.tiene_algun_alcance:
        raise PermissionDenied(
            'No tiene el permiso requerido: "usuario.ver".'
        )

    consulta = _consulta_usuarios_segun_alcance(alcances)
    return consulta.order_by("correo", "id")


def _consulta_usuarios_segun_alcance(alcances):
    roles_activos = RolUsuario.objetos.filter(
        activo=True,
        rol__activo=True,
    ).select_related("rol", "empresa", "sucursal")
    consulta = (
        Usuario.objetos.select_related("empresa", "sucursal")
        .prefetch_related(
            Prefetch("asignaciones_roles", queryset=roles_activos)
        )
    )
    if alcances.global_:
        return consulta
    return consulta.filter(
        Q(empresa_id__in=alcances.empresas)
        | Q(sucursal_id__in=alcances.sucursales)
    ).distinct()


def obtener_usuario_autorizado(
    usuario,
    identificador_usuario,
    codigo_permiso="usuario.ver",
):
    """Obtiene un usuario sin revelar identidades fuera del alcance."""
    alcances = obtener_alcances_permiso(usuario, codigo_permiso)
    if not alcances.tiene_algun_alcance:
        raise PermissionDenied(
            f'No tiene el permiso requerido: "{codigo_permiso}".'
        )
    try:
        return _consulta_usuarios_segun_alcance(alcances).get(
            id=identificador_usuario
        )
    except (Usuario.DoesNotExist, ValueError) as error:
        raise Http404(
            "El usuario no existe o no está dentro de su alcance."
        ) from error


def listar_asignaciones_roles_usuario_autorizadas(
    usuario,
    identificador_usuario,
):
    """Lista el historial de roles visible sin exponer otros alcances."""
    obtener_usuario_autorizado(usuario, identificador_usuario)
    alcances = obtener_alcances_permiso(usuario, "usuario.ver")
    consulta = RolUsuario.objetos.filter(
        usuario_id=identificador_usuario,
    ).select_related(
        "rol",
        "empresa",
        "sucursal",
        "asignado_por",
        "revocado_por",
    )
    if not alcances.global_:
        consulta = consulta.filter(
            Q(
                tipo_alcance=TipoAlcanceRol.EMPRESA,
                empresa_id__in=alcances.empresas,
            )
            | Q(
                tipo_alcance=TipoAlcanceRol.SUCURSAL,
                empresa_id__in=alcances.empresas,
            )
            | Q(
                tipo_alcance=TipoAlcanceRol.SUCURSAL,
                sucursal_id__in=alcances.sucursales,
            )
        )
    return consulta.order_by("-activo", "rol__nombre", "-asignado_en")
