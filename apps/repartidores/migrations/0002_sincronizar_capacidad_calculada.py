from django.db import migrations


ESTADOS_ACTIVOS = (
    "ASSIGNED",
    "GOING_TO_PICKUP",
    "AT_PICKUP",
    "PICKED_UP",
    "IN_TRANSIT",
    "AT_DESTINATION",
)


def sincronizar_capacidades(apps, schema_editor):
    Repartidor = apps.get_model("repartidores", "Repartidor")
    Solicitud = apps.get_model("solicitudes", "Solicitud")
    alias = schema_editor.connection.alias
    for identificador in Repartidor.objects.using(alias).values_list("id", flat=True).iterator():
        cantidad = Solicitud.objects.using(alias).filter(
            repartidor_asignado_id=identificador,
            estado__in=ESTADOS_ACTIVOS,
        ).count()
        capacidad = (
            "EMPTY" if cantidad == 0
            else "FULL" if cantidad >= 5
            else "AVAILABLE_SPACE"
        )
        Repartidor.objects.using(alias).filter(id=identificador).update(
            capacidad=capacidad
        )


class Migration(migrations.Migration):
    dependencies = [
        ("repartidores", "0001_initial"),
        ("solicitudes", "0005_modalidades_y_movimiento_especial"),
    ]
    operations = [migrations.RunPython(sincronizar_capacidades, migrations.RunPython.noop)]
