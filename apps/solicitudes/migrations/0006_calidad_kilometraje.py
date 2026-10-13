from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("solicitudes", "0005_modalidades_y_movimiento_especial")]
    operations = [
        migrations.AddField(model_name="movimientoenvioespecial", name="calidad_kilometraje", field=models.JSONField(blank=True, default=dict)),
    ]
