"""Rol operativo vigente, compartido por selección y validación de motoristas."""

from django.conf import settings
from django.db.models import Exists, OuterRef

from apps.usuarios.models import RolUsuario
from apps.usuarios.opciones import TipoAlcanceRol


def roles_operativos_vigentes(usuario_id, empresa_id):
    """Acepta identificadores u OuterRef para reutilizar la misma condición SQL."""
    consulta = RolUsuario.objetos.filter(
        usuario_id=usuario_id, activo=True, rol__activo=True,
    )
    if settings.MODO_APLICACION == "CORPORATIVO":
        return consulta.filter(
            rol__codigo="REPARTIDOR_CORPORATIVO",
            tipo_alcance=TipoAlcanceRol.EMPRESA,
            empresa_id=empresa_id,
            empresa__isnull=False,
            usuario__empresa_id=empresa_id,
        )
    if settings.MODO_APLICACION == "EXTERNO":
        return consulta.filter(
            rol__codigo="REPARTIDOR_RED",
            tipo_alcance=TipoAlcanceRol.GLOBAL,
            usuario__empresa__isnull=True,
            usuario__perfil_repartidor__empresa__isnull=True,
        )
    return consulta.none()


def anotar_rol_operativo(consulta):
    return consulta.annotate(
        tiene_rol_operativo_vigente=Exists(
            roles_operativos_vigentes(OuterRef("usuario_id"), OuterRef("empresa_id"))
        ),
    )


def tiene_rol_operativo_repartidor(repartidor):
    vigente = getattr(repartidor, "tiene_rol_operativo_vigente", None)
    if vigente is None:
        vigente = roles_operativos_vigentes(
            repartidor.usuario_id, repartidor.empresa_id,
        ).exists()
    return vigente
