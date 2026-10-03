from django.db import migrations


PERMISOS_NUEVOS = {
    "solicitud.ver_propias": (
        "Ver solicitudes propias",
        "Consultar únicamente solicitudes creadas por el usuario.",
    ),
    "solicitud.ver_asignadas": (
        "Ver solicitudes asignadas",
        "Consultar únicamente solicitudes asignadas al repartidor.",
    ),
}

ROLES_SOLICITANTES = {
    "SOLICITANTE_CORPORATIVO",
    "SOLICITANTE_EXTERNO",
}

ROLES_REPARTIDORES = {
    "REPARTIDOR_CORPORATIVO",
    "REPARTIDOR_RED",
}


def separar_visibilidad_solicitudes(aplicaciones, editor_esquema):
    Rol = aplicaciones.get_model("usuarios", "Rol")
    Permiso = aplicaciones.get_model("usuarios", "Permiso")
    PermisoRol = aplicaciones.get_model("usuarios", "PermisoRol")

    permisos = {}
    for codigo, (nombre, descripcion) in PERMISOS_NUEVOS.items():
        permiso, _ = Permiso._default_manager.update_or_create(
            codigo=codigo,
            defaults={
                "nombre": nombre,
                "descripcion": descripcion,
                "activo": True,
            },
        )
        permisos[codigo] = permiso

    rol_por_codigo = {
        rol.codigo: rol
        for rol in Rol._default_manager.filter(
            codigo__in=ROLES_SOLICITANTES | ROLES_REPARTIDORES
        )
    }
    permiso_general = Permiso._default_manager.get(codigo="solicitud.ver")
    for codigo_rol, rol in rol_por_codigo.items():
        PermisoRol._default_manager.filter(
            rol=rol,
            permiso=permiso_general,
        ).update(activo=False)
        codigo_permiso = (
            "solicitud.ver_propias"
            if codigo_rol in ROLES_SOLICITANTES
            else "solicitud.ver_asignadas"
        )
        PermisoRol._default_manager.update_or_create(
            rol=rol,
            permiso=permisos[codigo_permiso],
            defaults={"activo": True},
        )


def restaurar_visibilidad_general(aplicaciones, editor_esquema):
    Rol = aplicaciones.get_model("usuarios", "Rol")
    Permiso = aplicaciones.get_model("usuarios", "Permiso")
    PermisoRol = aplicaciones.get_model("usuarios", "PermisoRol")

    roles = Rol._default_manager.filter(
        codigo__in=ROLES_SOLICITANTES | ROLES_REPARTIDORES
    )
    permiso_general = Permiso._default_manager.get(codigo="solicitud.ver")
    PermisoRol._default_manager.filter(
        rol__in=roles,
        permiso=permiso_general,
    ).update(activo=True)
    PermisoRol._default_manager.filter(
        rol__in=roles,
        permiso__codigo__in=PERMISOS_NUEVOS,
    ).update(activo=False)


class Migration(migrations.Migration):
    dependencies = [
        ("usuarios", "0004_catalogo_inicial_autorizacion"),
    ]

    operations = [
        migrations.RunPython(
            separar_visibilidad_solicitudes,
            restaurar_visibilidad_general,
        ),
    ]
