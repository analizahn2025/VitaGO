"""Administración segura de usuarios, roles y alcances."""

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.autenticacion.servicios.sesiones import (
    cerrar_todas_las_sesiones,
    revocar_sesiones_usuario_inactivo,
)
from apps.organizaciones.models import Empresa, Sucursal
from apps.organizaciones.opciones import EstadoOrganizacion
from apps.usuarios.models import Permiso, PermisoRol, Rol, RolUsuario, Usuario
from apps.usuarios.opciones import EstadoUsuario, TipoAlcanceRol
from apps.usuarios.servicios.permisos import usuario_tiene_permiso


ROLES_POR_MODO = {
    "CORPORATIVO": {
        "SUPERADMINISTRADOR",
        "ADMINISTRADOR_CORPORATIVO",
        "GERENTE_OPERACIONES",
        "SOLICITANTE_CORPORATIVO",
        "REPARTIDOR_CORPORATIVO",
    },
    "EXTERNO": {
        "SUPERADMINISTRADOR",
        "ADMINISTRADOR_EMPRESA_EXTERNA",
        "SOLICITANTE_EXTERNO",
        "OPERADOR_RED",
        "REPARTIDOR_RED",
    },
}

ROLES_DELEGABLES = {
    "ADMINISTRADOR_CORPORATIVO": {
        "ADMINISTRADOR_CORPORATIVO",
        "GERENTE_OPERACIONES",
        "SOLICITANTE_CORPORATIVO",
        "REPARTIDOR_CORPORATIVO",
    },
    "GERENTE_OPERACIONES": {
        "SOLICITANTE_CORPORATIVO",
        "REPARTIDOR_CORPORATIVO",
    },
    "ADMINISTRADOR_EMPRESA_EXTERNA": {
        "ADMINISTRADOR_EMPRESA_EXTERNA",
        "SOLICITANTE_EXTERNO",
    },
}

PERMISOS_ADMINISTRATIVOS = frozenset(
    {"usuario.administrar", "rol.asignar"}
)


def _resolver_contexto_alcance(tipo_alcance, empresa_id=None, sucursal_id=None):
    empresa = None
    sucursal = None

    if tipo_alcance == TipoAlcanceRol.GLOBAL:
        if empresa_id or sucursal_id:
            raise ValidationError(
                "El alcance global no admite empresa ni sucursal."
            )
        return empresa, sucursal

    if not empresa_id:
        raise ValidationError(
            {"empresa_id": "La empresa es obligatoria para este alcance."}
        )
    try:
        empresa = Empresa.objects.get(
            id=empresa_id,
            estado=EstadoOrganizacion.ACTIVO,
        )
    except (Empresa.DoesNotExist, ValueError) as error:
        raise Http404("La empresa no existe o está inactiva.") from error

    if tipo_alcance == TipoAlcanceRol.EMPRESA:
        if sucursal_id:
            raise ValidationError(
                {"sucursal_id": "El alcance de empresa no admite sucursal."}
            )
        return empresa, sucursal

    if tipo_alcance != TipoAlcanceRol.SUCURSAL:
        raise ValidationError({"tipo_alcance": "El alcance no es válido."})
    if not sucursal_id:
        raise ValidationError(
            {"sucursal_id": "La sucursal es obligatoria para este alcance."}
        )
    try:
        sucursal = Sucursal.objects.get(
            id=sucursal_id,
            empresa_id=empresa.id,
            estado=EstadoOrganizacion.ACTIVO,
        )
    except (Sucursal.DoesNotExist, ValueError) as error:
        raise Http404(
            "La sucursal no existe, está inactiva o no pertenece a la empresa."
        ) from error
    return empresa, sucursal


def _usuario_tiene_permiso_en_contexto(usuario, codigo, empresa, sucursal):
    return usuario_tiene_permiso(
        usuario,
        codigo,
        empresa=empresa,
        sucursal=sucursal,
    )


def _exigir_administracion(usuario, empresa, sucursal):
    for codigo in ("usuario.administrar", "rol.asignar"):
        if not _usuario_tiene_permiso_en_contexto(
            usuario,
            codigo,
            empresa,
            sucursal,
        ):
            raise PermissionDenied(
                f'No tiene el permiso requerido: "{codigo}" en este alcance.'
            )


def _exigir_administracion_usuario(usuario_administrador, usuario_objetivo):
    if not _usuario_tiene_permiso_en_contexto(
        usuario_administrador,
        "usuario.administrar",
        usuario_objetivo.empresa,
        usuario_objetivo.sucursal,
    ):
        raise PermissionDenied(
            'No tiene el permiso requerido: "usuario.administrar" en este alcance.'
        )
    if usuario_administrador.es_superusuario:
        return

    roles_delegadores = _roles_delegadores_en_contexto(
        usuario_administrador,
        usuario_objetivo.empresa,
        usuario_objetivo.sucursal,
    )
    if not roles_delegadores or "GERENTE_OPERACIONES" not in roles_delegadores:
        return
    if roles_delegadores & {
        "SUPERADMINISTRADOR",
        "ADMINISTRADOR_CORPORATIVO",
    }:
        return

    codigos_permitidos = ROLES_DELEGABLES["GERENTE_OPERACIONES"]
    posee_rol_superior = RolUsuario.objetos.filter(
        usuario=usuario_objetivo,
        activo=True,
        rol__activo=True,
    ).exclude(rol__codigo__in=codigos_permitidos).exists()
    if usuario_objetivo.es_superusuario or posee_rol_superior:
        raise PermissionDenied(
            "El gerente de operaciones solo puede administrar usuarios operativos."
        )


def _rol_es_compatible_con_modo(rol):
    return rol.codigo in ROLES_POR_MODO.get(settings.MODO_APLICACION, set())


def _rol_permite_alcance(rol, tipo_alcance):
    return {
        TipoAlcanceRol.GLOBAL: rol.permite_alcance_global,
        TipoAlcanceRol.EMPRESA: rol.permite_alcance_empresa,
        TipoAlcanceRol.SUCURSAL: rol.permite_alcance_sucursal,
    }.get(tipo_alcance, False)


def _validar_alcance_usuario(usuario_objetivo, tipo_alcance, empresa, sucursal):
    if tipo_alcance == TipoAlcanceRol.GLOBAL:
        return
    if usuario_objetivo.empresa_id != empresa.id:
        raise ValidationError(
            {
                "empresa_id": (
                    "El alcance debe pertenecer a la empresa del usuario."
                )
            }
        )
    if (
        tipo_alcance == TipoAlcanceRol.SUCURSAL
        and usuario_objetivo.sucursal_id
        and usuario_objetivo.sucursal_id != sucursal.id
    ):
        raise ValidationError(
            {
                "sucursal_id": (
                    "El alcance debe pertenecer a la sucursal del usuario."
                )
            }
        )


def _rol_es_administrativo(rol):
    cantidad = (
        PermisoRol.objetos.filter(
            rol=rol,
            activo=True,
            permiso__activo=True,
            permiso__codigo__in=PERMISOS_ADMINISTRATIVOS,
        )
        .values("permiso__codigo")
        .distinct()
        .count()
    )
    return cantidad == len(PERMISOS_ADMINISTRATIVOS)


def _identificadores_roles_administrativos():
    return (
        PermisoRol.objetos.filter(
            activo=True,
            permiso__activo=True,
            permiso__codigo__in=PERMISOS_ADMINISTRATIVOS,
            rol__activo=True,
            rol__codigo__in=ROLES_POR_MODO.get(
                settings.MODO_APLICACION,
                set(),
            ),
        )
        .values("rol_id")
        .annotate(cantidad_permisos=Count("permiso_id", distinct=True))
        .filter(cantidad_permisos=len(PERMISOS_ADMINISTRATIVOS))
        .values("rol_id")
    )


def _bloquear_revocaciones_administrativas():
    """Serializa la comprobación que evita dejar alcances sin administrador."""
    Permiso.objetos.select_for_update().get(codigo="rol.asignar")


def _existe_otro_administrador(asignacion, usuario_id=None):
    consulta = RolUsuario.objetos.filter(
        activo=True,
        rol_id__in=_identificadores_roles_administrativos(),
    ).exclude(pk=asignacion.pk)
    if usuario_id is not None:
        consulta = consulta.filter(usuario_id=usuario_id)

    if asignacion.tipo_alcance == TipoAlcanceRol.GLOBAL:
        consulta = consulta.filter(tipo_alcance=TipoAlcanceRol.GLOBAL)
    elif asignacion.tipo_alcance == TipoAlcanceRol.EMPRESA:
        consulta = consulta.filter(
            Q(tipo_alcance=TipoAlcanceRol.GLOBAL)
            | Q(
                tipo_alcance=TipoAlcanceRol.EMPRESA,
                empresa_id=asignacion.empresa_id,
            )
        )
    else:
        consulta = consulta.filter(
            Q(tipo_alcance=TipoAlcanceRol.GLOBAL)
            | Q(
                tipo_alcance=TipoAlcanceRol.EMPRESA,
                empresa_id=asignacion.empresa_id,
            )
            | Q(
                tipo_alcance=TipoAlcanceRol.SUCURSAL,
                sucursal_id=asignacion.sucursal_id,
            )
        )
    return consulta.exists()


def _roles_delegadores_en_contexto(usuario, empresa, sucursal):
    if usuario.es_superusuario:
        return None

    filtro_alcance = Q(tipo_alcance=TipoAlcanceRol.GLOBAL)
    if empresa is not None:
        filtro_alcance |= Q(
            tipo_alcance=TipoAlcanceRol.EMPRESA,
            empresa_id=empresa.id,
        )
    if sucursal is not None:
        filtro_alcance |= Q(
            tipo_alcance=TipoAlcanceRol.SUCURSAL,
            sucursal_id=sucursal.id,
        )

    return set(
        RolUsuario.objetos.filter(
            usuario_id=usuario.pk,
            activo=True,
            rol__activo=True,
        )
        .filter(filtro_alcance)
        .values_list("rol__codigo", flat=True)
        .distinct()
    )


def _puede_asignar_rol(
    usuario,
    rol,
    tipo_alcance,
    empresa,
    sucursal,
    roles_delegadores=None,
):
    if not _rol_es_compatible_con_modo(rol):
        return False
    if not _rol_permite_alcance(rol, tipo_alcance):
        return False
    if usuario.es_superusuario:
        return True

    if roles_delegadores is None:
        roles_delegadores = _roles_delegadores_en_contexto(
            usuario,
            empresa,
            sucursal,
        )
    if "SUPERADMINISTRADOR" in roles_delegadores:
        return True
    codigos_delegables = set()
    for codigo_rol in roles_delegadores:
        codigos_delegables.update(ROLES_DELEGABLES.get(codigo_rol, set()))
    return rol.codigo in codigos_delegables


def listar_roles_asignables(
    usuario,
    *,
    tipo_alcance,
    empresa_id=None,
    sucursal_id=None,
):
    """Devuelve únicamente roles que el usuario puede conceder sin escalar."""
    empresa, sucursal = _resolver_contexto_alcance(
        tipo_alcance,
        empresa_id,
        sucursal_id,
    )
    _exigir_administracion(usuario, empresa, sucursal)
    roles_delegadores = _roles_delegadores_en_contexto(
        usuario,
        empresa,
        sucursal,
    )
    roles = Rol.objetos.filter(activo=True).order_by("nombre", "id")
    return [
        rol
        for rol in roles
        if _puede_asignar_rol(
            usuario,
            rol,
            tipo_alcance,
            empresa,
            sucursal,
            roles_delegadores,
        )
    ]


@transaction.atomic
def crear_usuario_administrado(usuario_administrador, datos_validados):
    """Crea el usuario y su primer rol dentro de una sola transacción."""
    datos = dict(datos_validados)
    tipo_alcance = datos.pop("tipo_alcance")
    empresa_id = datos.pop("empresa_id", None)
    sucursal_id = datos.pop("sucursal_id", None)
    codigo_rol = datos.pop("rol_codigo")
    contrasena = datos.pop("contrasena_temporal", None)

    empresa, sucursal = _resolver_contexto_alcance(
        tipo_alcance,
        empresa_id,
        sucursal_id,
    )
    _exigir_administracion(usuario_administrador, empresa, sucursal)

    try:
        rol = Rol.objetos.get(codigo=codigo_rol, activo=True)
    except Rol.DoesNotExist as error:
        raise ValidationError({"rol_codigo": "El rol indicado no existe."}) from error
    roles_delegadores = _roles_delegadores_en_contexto(
        usuario_administrador,
        empresa,
        sucursal,
    )
    if not _puede_asignar_rol(
        usuario_administrador,
        rol,
        tipo_alcance,
        empresa,
        sucursal,
        roles_delegadores,
    ):
        raise PermissionDenied(
            "No puede asignar este rol en el alcance solicitado."
        )

    datos["empresa"] = empresa
    datos["sucursal"] = sucursal
    if Usuario.objetos.filter(correo=datos["correo"]).exists():
        raise ValidationError(
            {"correo": "Ya existe un usuario con este correo."}
        )
    identificador_externo = datos.get("identificador_autenticacion_externa")
    if identificador_externo and Usuario.objetos.filter(
        identificador_autenticacion_externa=identificador_externo
    ).exists():
        raise ValidationError(
            {
                "identificador_autenticacion_externa": (
                    "Ya existe un usuario con este identificador externo."
                )
            }
        )

    try:
        nuevo_usuario = Usuario.objetos.create_user(
            password=contrasena,
            **datos,
        )
    except IntegrityError as error:
        raise ValidationError(
            "No fue posible crear el usuario porque su identidad ya existe."
        ) from error

    RolUsuario.objetos.create(
        usuario=nuevo_usuario,
        rol=rol,
        tipo_alcance=tipo_alcance,
        empresa=empresa,
        sucursal=sucursal,
        asignado_por=usuario_administrador,
    )
    return nuevo_usuario


@transaction.atomic
def asignar_rol_usuario(
    usuario_administrador,
    usuario_objetivo,
    datos_validados,
):
    """Asigna un rol sin permitir duplicados ni escalación de privilegios."""
    datos = dict(datos_validados)
    tipo_alcance = datos["tipo_alcance"]
    empresa, sucursal = _resolver_contexto_alcance(
        tipo_alcance,
        datos.get("empresa_id"),
        datos.get("sucursal_id"),
    )
    usuario_bloqueado = Usuario.objetos.select_for_update().get(
        pk=usuario_objetivo.pk
    )
    _exigir_administracion_usuario(usuario_administrador, usuario_bloqueado)
    _exigir_administracion(usuario_administrador, empresa, sucursal)
    _validar_alcance_usuario(
        usuario_bloqueado,
        tipo_alcance,
        empresa,
        sucursal,
    )

    try:
        rol = Rol.objetos.get(codigo=datos["rol_codigo"], activo=True)
    except Rol.DoesNotExist as error:
        raise ValidationError(
            {"rol_codigo": "El rol indicado no existe."}
        ) from error
    if not _puede_asignar_rol(
        usuario_administrador,
        rol,
        tipo_alcance,
        empresa,
        sucursal,
    ):
        raise PermissionDenied(
            "No puede asignar este rol en el alcance solicitado."
        )

    filtros_duplicado = {
        "usuario": usuario_bloqueado,
        "rol": rol,
        "tipo_alcance": tipo_alcance,
        "activo": True,
    }
    if tipo_alcance == TipoAlcanceRol.EMPRESA:
        filtros_duplicado["empresa"] = empresa
    elif tipo_alcance == TipoAlcanceRol.SUCURSAL:
        filtros_duplicado["sucursal"] = sucursal
    if RolUsuario.objetos.filter(**filtros_duplicado).exists():
        raise ValidationError(
            {"rol_codigo": "El usuario ya posee este rol en el alcance indicado."}
        )

    try:
        return RolUsuario.objetos.create(
            usuario=usuario_bloqueado,
            rol=rol,
            tipo_alcance=tipo_alcance,
            empresa=empresa,
            sucursal=sucursal,
            asignado_por=usuario_administrador,
        )
    except IntegrityError as error:
        raise ValidationError(
            {"rol_codigo": "El usuario ya posee este rol en el alcance indicado."}
        ) from error


@transaction.atomic
def revocar_rol_usuario(
    usuario_administrador,
    usuario_objetivo,
    identificador_asignacion,
):
    """Revoca un rol, conserva su historial y protege administradores."""
    usuario_bloqueado = Usuario.objetos.select_for_update().get(
        pk=usuario_objetivo.pk
    )
    _exigir_administracion_usuario(usuario_administrador, usuario_bloqueado)
    try:
        asignacion = (
            RolUsuario.objetos.select_for_update()
            .select_related("rol")
            .get(
                pk=identificador_asignacion,
                usuario=usuario_bloqueado,
                activo=True,
            )
        )
    except (RolUsuario.DoesNotExist, ValueError) as error:
        raise Http404(
            "La asignación de rol no existe o ya fue revocada."
        ) from error

    _exigir_administracion(
        usuario_administrador,
        asignacion.empresa,
        asignacion.sucursal,
    )
    if not _puede_asignar_rol(
        usuario_administrador,
        asignacion.rol,
        asignacion.tipo_alcance,
        asignacion.empresa,
        asignacion.sucursal,
    ):
        raise PermissionDenied(
            "No puede revocar este rol en el alcance solicitado."
        )

    if _rol_es_administrativo(asignacion.rol):
        _bloquear_revocaciones_administrativas()
        if (
            usuario_bloqueado.pk == usuario_administrador.pk
            and not _existe_otro_administrador(
                asignacion,
                usuario_id=usuario_bloqueado.pk,
            )
        ):
            raise ValidationError(
                "No puede revocar su último rol administrativo en este alcance."
            )
        if not _existe_otro_administrador(asignacion):
            raise ValidationError(
                "No puede dejar este alcance sin un administrador."
            )

    asignacion.activo = False
    asignacion.revocado_por = usuario_administrador
    asignacion.revocado_en = timezone.now()
    asignacion.save(
        update_fields=(
            "activo",
            "revocado_por",
            "revocado_en",
            "actualizado_en",
        )
    )
    cerrar_todas_las_sesiones(usuario_bloqueado)
    return asignacion


@transaction.atomic
def actualizar_usuario_administrado(
    usuario_administrador,
    usuario_objetivo,
    cambios,
):
    """Actualiza datos básicos y revoca sesiones si deja de estar activo."""
    usuario_bloqueado = Usuario.objetos.select_for_update().get(
        pk=usuario_objetivo.pk
    )
    _exigir_administracion_usuario(usuario_administrador, usuario_bloqueado)

    estado_nuevo = cambios.get("estado", usuario_bloqueado.estado)
    if (
        usuario_bloqueado.pk == usuario_administrador.pk
        and estado_nuevo != usuario_bloqueado.estado
        and estado_nuevo != EstadoUsuario.ACTIVO
    ):
        raise ValidationError(
            {"estado": "No puede suspender o desactivar su propia cuenta."}
        )

    estado_anterior = usuario_bloqueado.estado
    for campo, valor in cambios.items():
        setattr(usuario_bloqueado, campo, valor)
    usuario_bloqueado.save(
        update_fields=(*cambios.keys(), "actualizado_en")
    )

    if (
        estado_anterior != estado_nuevo
        and estado_nuevo != EstadoUsuario.ACTIVO
    ):
        revocar_sesiones_usuario_inactivo(usuario_bloqueado)
    return usuario_bloqueado


@transaction.atomic
def restablecer_contrasena_usuario(
    usuario_administrador,
    usuario_objetivo,
    contrasena_temporal,
):
    """Cambia la contraseña local y revoca todas las sesiones anteriores."""
    if settings.PROVEEDOR_AUTENTICACION != "LOCAL":
        raise Http404(
            "El restablecimiento local no está disponible con este proveedor."
        )

    usuario_bloqueado = Usuario.objetos.select_for_update().get(
        pk=usuario_objetivo.pk
    )
    _exigir_administracion_usuario(usuario_administrador, usuario_bloqueado)
    usuario_bloqueado.set_password(contrasena_temporal)
    usuario_bloqueado.save(update_fields=("password", "actualizado_en"))
    cerrar_todas_las_sesiones(usuario_bloqueado)
