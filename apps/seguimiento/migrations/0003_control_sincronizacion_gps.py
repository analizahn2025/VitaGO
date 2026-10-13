import uuid

from django.db import migrations, models
from django.db.models.deletion import PROTECT


class Migration(migrations.Migration):
    dependencies = [
        ("jornadas", "0003_calidad_kilometraje"),
        ("repartidores", "0002_sincronizar_capacidad_calculada"),
        ("seguimiento", "0002_movimiento_envio_especial"),
        ("solicitudes", "0006_calidad_kilometraje"),
    ]
    operations = [
        migrations.AddField(model_name="registroubicacion", name="secuencia", field=models.PositiveBigIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="registroubicacion", name="sesion_gps", field=models.UUIDField(blank=True, null=True)),
        migrations.AddConstraint(model_name="registroubicacion", constraint=models.UniqueConstraint(fields=("repartidor", "sesion_gps", "secuencia"), name="reg_ubi_sesion_secuencia_uniq")),
        migrations.AddConstraint(model_name="registroubicacion", constraint=models.CheckConstraint(
            condition=models.Q(sesion_gps__isnull=True, secuencia__isnull=True) | models.Q(sesion_gps__isnull=False, secuencia__isnull=False, secuencia__gte=1),
            name="reg_ubi_secuencia_pareja_ck",
        )),
        migrations.CreateModel(
            name="RevisionKilometraje",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("actualizado_en", models.DateTimeField(auto_now=True)),
                ("numero", models.PositiveIntegerField()),
                ("motivo", models.CharField(max_length=32)),
                ("kilometros", models.DecimalField(decimal_places=3, max_digits=12)),
                ("calidad", models.JSONField()),
                ("jornada", models.ForeignKey(on_delete=PROTECT, to="jornadas.jornadarepartidor")),
                ("movimiento_especial", models.ForeignKey(blank=True, null=True, on_delete=PROTECT, to="solicitudes.movimientoenvioespecial")),
            ],
            options={"db_table": "revisiones_kilometraje", "ordering": ("creado_en", "id")},
        ),
        migrations.AddConstraint(model_name="revisionkilometraje", constraint=models.UniqueConstraint(condition=models.Q(movimiento_especial__isnull=True), fields=("jornada", "numero"), name="revision_km_jornada_num_uniq")),
        migrations.AddConstraint(model_name="revisionkilometraje", constraint=models.UniqueConstraint(condition=models.Q(movimiento_especial__isnull=False), fields=("movimiento_especial", "numero"), name="revision_km_mov_num_uniq")),
    ]
