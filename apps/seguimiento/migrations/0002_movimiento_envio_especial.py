import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("seguimiento", "0001_initial"),
        ("solicitudes", "0005_modalidades_y_movimiento_especial"),
    ]

    operations = [
        migrations.AddField(
            model_name="registroubicacion",
            name="movimiento_envio_especial",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="registros_ubicacion",
                to="solicitudes.movimientoenvioespecial",
            ),
        ),
        migrations.AddIndex(
            model_name="registroubicacion",
            index=models.Index(
                fields=["movimiento_envio_especial", "registrada_en"],
                name="reg_ubi_mov_esp_fecha_idx",
            ),
        ),
    ]
