"""Consultas de autorización basadas en permisos y alcance."""

from dataclasses import dataclass

from django.db.models import Q

from apps.usuarios.models import RolUsuario
from apps.usuarios.opciones import TipoAlcanceRol


@dataclass(frozen=True, slots=True)
class AlcancesPermiso:
    """Alcances activos donde un usuario posee un permiso concreto."""

    global_: bool = False
    empresas: frozenset = frozenset()
    sucursales: frozenset = frozenset()
    empresas_de_sucursales: frozenset = frozenset()

    @property
    def tiene_algun_alcance(self):
        return bool(self.global_ or self.empresas or self.sucursales)

    @property
    def empresas_visibles(self):
        return self.empresas | self.empresas_de_sucursales

    def permite_empresa(self, identificador_empresa):
        return self.global_ or identificador_empresa in self.empresas_visibles

    def permite_todas_las_sucursales_de(self, identificador_empresa):
        return self.global_ or identificador_empresa in self.empresas

    def permite_sucursal(self, identificador_sucursal, identificador_empresa):
        return self.permite_todas_las_sucursales_de(
            identificador_empresa
        ) or identificador_sucursal in self.sucursales


def _obtener_identificador(valor):
    if valor is None:
        return None
    return getattr(valor, "pk", valor)


def obtener_alcances_permisos(usuario, codigos_permisos):
    """Lee varios permisos en una consulta, sin conservar autorizaciones en caché."""
    codigos = tuple(dict.fromkeys(codigo.strip().casefold() for codigo in codigos_permisos))
    vacios = {codigo: AlcancesPermiso() for codigo in codigos}
    if not codigos:
        return vacios
    if not usuario or not getattr(usuario, "is_authenticated", False):
        return vacios
    if not usuario.is_active:
        return vacios
    if usuario.es_superusuario:
        return {codigo: AlcancesPermiso(global_=True) for codigo in codigos}

    asignaciones = (
        RolUsuario.objetos.filter(
            usuario_id=usuario.pk,
            activo=True,
            rol__activo=True,
            rol__asignaciones_permisos__activo=True,
            rol__asignaciones_permisos__permiso__activo=True,
            rol__asignaciones_permisos__permiso__codigo__in=codigos,
        )
        .order_by()
        .values_list(
            "rol__asignaciones_permisos__permiso__codigo",
            "tipo_alcance",
            "empresa_id",
            "sucursal_id",
        )
        .distinct()
    )

    grupos = {codigo: {"global_": False, "empresas": set(), "sucursales": set(), "empresas_de_sucursales": set()}
              for codigo in codigos}
    for codigo, tipo_alcance, empresa_id, sucursal_id in asignaciones:
        grupo = grupos[codigo]
        if tipo_alcance == TipoAlcanceRol.GLOBAL:
            grupo["global_"] = True
        elif tipo_alcance == TipoAlcanceRol.EMPRESA and empresa_id:
            grupo["empresas"].add(empresa_id)
        elif tipo_alcance == TipoAlcanceRol.SUCURSAL and sucursal_id:
            grupo["sucursales"].add(sucursal_id)
            if empresa_id:
                grupo["empresas_de_sucursales"].add(empresa_id)

    return {codigo: AlcancesPermiso(global_=grupo["global_"], empresas=frozenset(grupo["empresas"]),
        sucursales=frozenset(grupo["sucursales"]), empresas_de_sucursales=frozenset(grupo["empresas_de_sucursales"]))
        for codigo, grupo in grupos.items()}


def obtener_alcances_permiso(usuario, codigo_permiso):
    """Conserva la consulta individual mediante la misma regla de agrupación."""
    codigo = codigo_permiso.strip().casefold()
    return obtener_alcances_permisos(usuario, (codigo,))[codigo]


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
    if usuario.es_superusuario:
        return True

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
