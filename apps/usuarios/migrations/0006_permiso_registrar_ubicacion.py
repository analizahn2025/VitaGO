from django.db import migrations


CODIGO_PERMISO = "repartidor.registrar_ubicacion"
ROLES_REPARTIDORES = (
    "REPARTIDOR_CORPORATIVO",
    "REPARTIDOR_RED",
)


def agregar_permiso_registrar_ubicacion(aplicaciones, editor_esquema):
    Rol = aplicaciones.get_model("usuarios", "Rol")
    Permiso = aplicaciones.get_model("usuarios", "Permiso")
    PermisoRol = aplicaciones.get_model("usuarios", "PermisoRol")

    permiso, _ = Permiso._default_manager.update_or_create(
        codigo=CODIGO_PERMISO,
        defaults={
            "nombre": "Registrar ubicacion propia",
            "descripcion": (
                "Registrar puntos GPS del motorista durante su jornada."
            ),
            "activo": True,
        },
    )
    for rol in Rol._default_manager.filter(codigo__in=ROLES_REPARTIDORES):
        PermisoRol._default_manager.update_or_create(
            rol=rol,
            permiso=permiso,
            defaults={"activo": True},
        )


def desactivar_permiso_registrar_ubicacion(aplicaciones, editor_esquema):
    Permiso = aplicaciones.get_model("usuarios", "Permiso")
    PermisoRol = aplicaciones.get_model("usuarios", "PermisoRol")

    PermisoRol._default_manager.filter(
        rol__codigo__in=ROLES_REPARTIDORES,
        permiso__codigo=CODIGO_PERMISO,
    ).update(activo=False)
    permiso = Permiso._default_manager.filter(codigo=CODIGO_PERMISO).first()
    if permiso and not PermisoRol._default_manager.filter(
        permiso=permiso,
        activo=True,
    ).exists():
        permiso.activo = False
        permiso.save(update_fields=("activo", "actualizado_en"))


class Migration(migrations.Migration):
    dependencies = [
        ("usuarios", "0005_visibilidad_solicitudes_por_responsabilidad"),
    ]

    operations = [
        migrations.RunPython(
            agregar_permiso_registrar_ubicacion,
            desactivar_permiso_registrar_ubicacion,
        ),
    ]
