from django.db import migrations


ROLES = ("REPARTIDOR_CORPORATIVO", "REPARTIDOR_RED")


def agregar_permiso(apps, schema_editor):
    alias = schema_editor.connection.alias
    Permiso = apps.get_model("usuarios", "Permiso")
    Rol = apps.get_model("usuarios", "Rol")
    PermisoRol = apps.get_model("usuarios", "PermisoRol")
    permiso, _ = Permiso._default_manager.using(alias).update_or_create(
        codigo="ruta.calcular", defaults={"nombre": "Calcular ruta propia",
        "descripcion": "Solicitar explícitamente el trazado inicial dentro del presupuesto del backend.", "activo": True},
    )
    for rol in Rol._default_manager.using(alias).filter(codigo__in=ROLES):
        PermisoRol._default_manager.using(alias).update_or_create(
            rol=rol, permiso=permiso, defaults={"activo": True},
        )


def retirar_permiso(apps, schema_editor):
    alias = schema_editor.connection.alias
    apps.get_model("usuarios", "PermisoRol")._default_manager.using(alias).filter(
        rol__codigo__in=ROLES, permiso__codigo="ruta.calcular",
    ).update(activo=False)
    apps.get_model("usuarios", "Permiso")._default_manager.using(alias).filter(codigo="ruta.calcular").update(activo=False)


class Migration(migrations.Migration):
    dependencies = [("usuarios", "0009_retirar_capacidad_manual")]
    operations = [migrations.RunPython(agregar_permiso, retirar_permiso)]
