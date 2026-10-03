import uuid
from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("jornadas", "0001_initial"),
        ("repartidores", "0001_initial"),
        (
            "solicitudes",
            "0004_eventosolicitud_latitud_eventosolicitud_longitud_and_more",
        ),
    ]

    operations = [
        migrations.CreateModel(
            name="MovimientoEnvioEspecial",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("creado_en", models.DateTimeField(auto_now_add=True)),
                ("actualizado_en", models.DateTimeField(auto_now=True)),
                (
                    "estado",
                    models.CharField(
                        choices=[
                            ("ACTIVO", "Activo"),
                            ("FINALIZADO", "Finalizado"),
                        ],
                        default="ACTIVO",
                        max_length=16,
                    ),
                ),
                ("iniciada_en", models.DateTimeField()),
                ("finalizada_en", models.DateTimeField(blank=True, null=True)),
                (
                    "latitud_inicio",
                    models.DecimalField(decimal_places=6, max_digits=9),
                ),
                (
                    "longitud_inicio",
                    models.DecimalField(decimal_places=6, max_digits=9),
                ),
                (
                    "latitud_fin",
                    models.DecimalField(
                        blank=True, decimal_places=6, max_digits=9, null=True
                    ),
                ),
                (
                    "longitud_fin",
                    models.DecimalField(
                        blank=True, decimal_places=6, max_digits=9, null=True
                    ),
                ),
                (
                    "kilometros_recorridos",
                    models.DecimalField(
                        decimal_places=3,
                        default=Decimal("0"),
                        max_digits=12,
                        validators=[
                            django.core.validators.MinValueValidator(Decimal("0"))
                        ],
                    ),
                ),
                ("registros_considerados", models.PositiveIntegerField(default=0)),
                ("registros_descartados", models.PositiveIntegerField(default=0)),
            ],
            options={
                "verbose_name": "movimiento de envío especial",
                "verbose_name_plural": "movimientos de envíos especiales",
                "db_table": "movimientos_envios_especiales",
                "ordering": ("-iniciada_en", "-id"),
            },
        ),
        migrations.AddField(
            model_name="solicitud",
            name="destino_especial",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="solicitud",
            name="modalidad",
            field=models.CharField(
                blank=True,
                choices=[
                    ("ABIERTO", "Abierto"),
                    ("ENTRE_SUCURSALES", "Entre sucursales"),
                    ("EMPRESA_TRANSPORTE", "Empresa de transporte"),
                    ("ESPECIAL", "Envío especial"),
                ],
                max_length=32,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="solicitud",
            name="destino",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="solicitudes_como_destino",
                to="ubicaciones.ubicacion",
            ),
        ),
        migrations.AddIndex(
            model_name="solicitud",
            index=models.Index(
                fields=["modalidad", "estado", "-creado_en"],
                name="solicitud_modal_est_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="solicitud",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(destino__isnull=False, modalidad__isnull=True)
                    | models.Q(
                        destino__isnull=True,
                        destino_especial__isnull=False,
                        modalidad="ESPECIAL",
                    )
                    | models.Q(
                        destino__isnull=False,
                        destino_especial__isnull=True,
                        modalidad__in=(
                            "ABIERTO",
                            "ENTRE_SUCURSALES",
                            "EMPRESA_TRANSPORTE",
                        ),
                    )
                ),
                name="solicitud_destino_modalidad_ck",
            ),
        ),
        migrations.AddField(
            model_name="movimientoenvioespecial",
            name="jornada",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="movimientos_envios_especiales",
                to="jornadas.jornadarepartidor",
            ),
        ),
        migrations.AddField(
            model_name="movimientoenvioespecial",
            name="repartidor",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="movimientos_envios_especiales",
                to="repartidores.repartidor",
            ),
        ),
        migrations.AddField(
            model_name="movimientoenvioespecial",
            name="solicitud",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="movimiento_especial",
                to="solicitudes.solicitud",
            ),
        ),
        migrations.AddIndex(
            model_name="movimientoenvioespecial",
            index=models.Index(
                fields=["repartidor", "estado", "-iniciada_en"],
                name="mov_esp_repart_est_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="movimientoenvioespecial",
            constraint=models.UniqueConstraint(
                condition=models.Q(estado="ACTIVO"),
                fields=("repartidor",),
                name="mov_esp_repart_activo_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="movimientoenvioespecial",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        estado="ACTIVO",
                        finalizada_en__isnull=True,
                        latitud_fin__isnull=True,
                        longitud_fin__isnull=True,
                    )
                    | models.Q(
                        estado="FINALIZADO",
                        finalizada_en__isnull=False,
                        latitud_fin__isnull=False,
                        longitud_fin__isnull=False,
                    )
                ),
                name="mov_esp_cierre_valido_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="movimientoenvioespecial",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    latitud_inicio__gte=-90,
                    latitud_inicio__lte=90,
                    longitud_inicio__gte=-180,
                    longitud_inicio__lte=180,
                ),
                name="mov_esp_inicio_gps_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="movimientoenvioespecial",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(latitud_fin__isnull=True, longitud_fin__isnull=True)
                    | models.Q(
                        latitud_fin__gte=-90,
                        latitud_fin__lte=90,
                        longitud_fin__gte=-180,
                        longitud_fin__lte=180,
                    )
                ),
                name="mov_esp_fin_gps_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="movimientoenvioespecial",
            constraint=models.CheckConstraint(
                condition=models.Q(kilometros_recorridos__gte=0),
                name="mov_esp_km_no_negativos_ck",
            ),
        ),
    ]
