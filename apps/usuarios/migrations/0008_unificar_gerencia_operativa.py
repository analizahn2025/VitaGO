from django.db import migrations


ROL_GERENTE = "GERENTE_OPERACIONES"
ROL_SUPERVISOR = "SUPERVISOR_CORPORATIVO"
PERMISOS_ADMINISTRACION_USUARIOS = {
    "usuario.administrar",
    "rol.asignar",
}


def unificar_gerencia_operativa(aplicaciones, editor_esquema):
    Rol = aplicaciones.get_model("usuarios", "Rol")
    Permiso = aplicaciones.get_model("usuarios", "Permiso")
    PermisoRol = aplicaciones.get_model("usuarios", "PermisoRol")

    gerente = Rol._default_manager.get(codigo=ROL_GERENTE)
    Rol._default_manager.filter(pk=gerente.pk).update(
        activo=True,
        permite_alcance_global=False,
        permite_alcance_empresa=True,
        permite_alcance_sucursal=False,
        descripcion=(
            "Dirección operativa corporativa, administración de usuarios "
            "operativos y creación de envíos especiales."
        ),
    )
    permisos = Permiso._default_manager.filter(
        codigo__in=PERMISOS_ADMINISTRACION_USUARIOS,
        activo=True,
    )
    for permiso in permisos:
        PermisoRol._default_manager.update_or_create(
            rol_id=gerente.pk,
            permiso_id=permiso.pk,
            defaults={"activo": True},
        )

    supervisor = Rol._default_manager.filter(codigo=ROL_SUPERVISOR).first()
    if supervisor is not None:
        PermisoRol._default_manager.filter(rol_id=supervisor.pk).update(
            activo=False
        )
        Rol._default_manager.filter(pk=supervisor.pk).update(activo=False)


def restaurar_supervision_separada(aplicaciones, editor_esquema):
    Rol = aplicaciones.get_model("usuarios", "Rol")
    PermisoRol = aplicaciones.get_model("usuarios", "PermisoRol")

    gerente = Rol._default_manager.filter(codigo=ROL_GERENTE).first()
    if gerente is not None:
        PermisoRol._default_manager.filter(
            rol_id=gerente.pk,
            permiso__codigo__in=PERMISOS_ADMINISTRACION_USUARIOS,
        ).update(activo=False)

    supervisor = Rol._default_manager.filter(codigo=ROL_SUPERVISOR).first()
    if supervisor is not None:
        Rol._default_manager.filter(pk=supervisor.pk).update(activo=True)
        PermisoRol._default_manager.filter(rol_id=supervisor.pk).update(
            activo=True
        )


class Migration(migrations.Migration):
    dependencies = [("usuarios", "0007_gerente_operaciones")]

    operations = [
        migrations.RunPython(
            unificar_gerencia_operativa,
            restaurar_supervision_separada,
        )
    ]
