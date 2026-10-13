import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("rutas", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="ConsumoRutasGoogle",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("actualizado_en", models.DateTimeField(auto_now=True)),
                ("periodo", models.CharField(choices=[("DIARIO", "Diario"), ("MENSUAL", "Mensual")], max_length=10)),
                ("fecha", models.DateField()),
                ("intentos_reservados", models.PositiveIntegerField(default=0)),
            ],
            options={"db_table": "consumo_rutas_google", "constraints": [models.UniqueConstraint(fields=("periodo", "fecha"), name="consumo_google_periodo_uniq")]},
        ),
        migrations.CreateModel(
            name="CalculoRutaVial",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("actualizado_en", models.DateTimeField(auto_now=True)),
                ("estado", models.CharField(choices=[("CALCULANDO", "Calculando"), ("CALCULADA", "Calculada"), ("FALLIDA", "Fallida")], max_length=16)),
                ("intentos", models.PositiveIntegerField(default=1)),
                ("token_intento", models.UUIDField()),
                ("iniciada_en", models.DateTimeField()),
                ("calculada_en", models.DateTimeField(blank=True, null=True)),
                ("expira_en", models.DateTimeField(blank=True, null=True)),
                ("reintento_desde", models.DateTimeField(blank=True, null=True)),
                ("codigo_error", models.CharField(blank=True, max_length=40)),
                ("origen_gps", models.JSONField(default=dict)),
                ("paradas_calculadas", models.JSONField(default=list)),
                ("polilinea_codificada", models.TextField(blank=True)),
                ("version", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="calculo_vial", to="rutas.versionruta")),
            ],
            options={
                "db_table": "calculos_ruta_vial",
                "indexes": [models.Index(fields=["expira_en"], name="calculo_vial_expira_idx")],
                "constraints": [models.CheckConstraint(condition=models.Q(intentos__gte=1), name="calculo_vial_intentos_ck")],
            },
        ),
    ]
