import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("autenticacion", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="ControlIntentosInicioSesion",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("actualizado_en", models.DateTimeField(auto_now=True)),
                ("huella", models.CharField(max_length=64, unique=True)),
                ("intentos_fallidos", models.PositiveSmallIntegerField(default=0)),
                ("ventana_iniciada_en", models.DateTimeField()),
            ],
            options={
                "db_table": "controles_intentos_inicio_sesion",
                "verbose_name": "control de intentos de inicio de sesión",
                "verbose_name_plural": "controles de intentos de inicio de sesión",
                "constraints": [models.CheckConstraint(
                    condition=models.Q(intentos_fallidos__gte=0, intentos_fallidos__lte=10),
                    name="intentos_inicio_rango_ck",
                )],
            },
        ),
    ]
