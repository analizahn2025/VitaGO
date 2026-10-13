from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("jornadas", "0002_jornadarepartidor_kilometraje_disponible")]
    operations = [
        migrations.AddField(model_name="jornadarepartidor", name="calidad_kilometraje", field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name="jornadarepartidor", name="minutos_operativos", field=models.PositiveIntegerField(blank=True, null=True)),
    ]
