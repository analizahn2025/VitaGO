from django.db import migrations


def retirar_permiso(apps, schema_editor):
    Permiso = apps.get_model("usuarios", "Permiso")
    Permiso.objetos.filter(codigo="repartidor.actualizar_capacidad").update(
        activo=False
    )


class Migration(migrations.Migration):
    dependencies = [("usuarios", "0008_unificar_gerencia_operativa")]
    operations = [migrations.RunPython(retirar_permiso, migrations.RunPython.noop)]
