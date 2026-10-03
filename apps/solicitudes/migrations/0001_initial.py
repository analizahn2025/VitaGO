import uuid
from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("organizaciones", "0002_initial"),
        ("ubicaciones", "0002_catalogo_tipos_ubicacion"),
        ("usuarios", "0005_visibilidad_solicitudes_por_responsabilidad"),
    ]

    operations = [
        migrations.CreateModel(
            name="TipoServicio",
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
                ("codigo", models.CharField(max_length=64, unique=True)),
                ("nombre", models.CharField(max_length=150)),
                ("descripcion", models.TextField(blank=True, null=True)),
                ("activo", models.BooleanField(default=True)),
            ],
            options={
                "verbose_name": "tipo de servicio",
                "verbose_name_plural": "tipos de servicio",
                "db_table": "tipos_servicio",
                "ordering": ("nombre", "id"),
            },
        ),
        migrations.CreateModel(
            name="Solicitud",
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
                ("numero", models.CharField(max_length=32, unique=True)),
                (
                    "prioridad",
                    models.CharField(
                        choices=[
                            ("NORMAL", "Normal"),
                            ("PRIORITY", "Prioritaria"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "estado",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pendiente"),
                            ("ASSIGNED", "Asignada"),
                            ("GOING_TO_PICKUP", "Hacia recolección"),
                            ("AT_PICKUP", "En recolección"),
                            ("PICKED_UP", "Recolectada"),
                            ("IN_TRANSIT", "En tránsito"),
                            ("AT_DESTINATION", "En destino"),
                            ("DELIVERED", "Entregada"),
                            ("CANCELLED", "Cancelada"),
                            ("PICKUP_FAILED", "Recolección fallida"),
                            ("DELIVERY_FAILED", "Entrega fallida"),
                        ],
                        default="PENDING",
                        max_length=24,
                    ),
                ),
                ("notas", models.TextField(blank=True, null=True)),
                ("asignada_en", models.DateTimeField(blank=True, null=True)),
                (
                    "llegada_recoleccion_en",
                    models.DateTimeField(blank=True, null=True),
                ),
                ("recolectada_en", models.DateTimeField(blank=True, null=True)),
                (
                    "llegada_destino_en",
                    models.DateTimeField(blank=True, null=True),
                ),
                ("entregada_en", models.DateTimeField(blank=True, null=True)),
                ("cancelada_en", models.DateTimeField(blank=True, null=True)),
                (
                    "destino",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="solicitudes_como_destino",
                        to="ubicaciones.ubicacion",
                    ),
                ),
                (
                    "empresa",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="solicitudes",
                        to="organizaciones.empresa",
                    ),
                ),
                (
                    "origen",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="solicitudes_como_origen",
                        to="ubicaciones.ubicacion",
                    ),
                ),
                (
                    "solicitada_por",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="solicitudes_creadas",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "sucursal",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="solicitudes",
                        to="organizaciones.sucursal",
                    ),
                ),
                (
                    "tipo_servicio",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="solicitudes",
                        to="solicitudes.tiposervicio",
                    ),
                ),
            ],
            options={
                "verbose_name": "solicitud",
                "verbose_name_plural": "solicitudes",
                "db_table": "solicitudes",
                "ordering": ("-creado_en", "-id"),
            },
        ),
        migrations.CreateModel(
            name="EventoSolicitud",
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
                    "tipo",
                    models.CharField(
                        choices=[("CREADA", "Creada")],
                        max_length=80,
                    ),
                ),
                ("metadatos", models.JSONField(blank=True, default=dict)),
                (
                    "realizado_por",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="eventos_solicitudes_realizados",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "solicitud",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="eventos",
                        to="solicitudes.solicitud",
                    ),
                ),
            ],
            options={
                "verbose_name": "evento de solicitud",
                "verbose_name_plural": "eventos de solicitudes",
                "db_table": "eventos_solicitud",
                "ordering": ("creado_en", "id"),
                "indexes": [
                    models.Index(
                        fields=["solicitud", "creado_en"],
                        name="evt_sol_solic_creado_idx",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="ArticuloSolicitud",
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
                ("tipo_articulo", models.CharField(max_length=100)),
                ("descripcion", models.TextField(blank=True, null=True)),
                (
                    "cantidad",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("1"),
                        max_digits=12,
                        validators=[
                            django.core.validators.MinValueValidator(
                                Decimal("0.01")
                            )
                        ],
                    ),
                ),
                (
                    "codigo_referencia",
                    models.CharField(blank=True, max_length=120, null=True),
                ),
                (
                    "condicion_transporte",
                    models.CharField(blank=True, max_length=200, null=True),
                ),
                ("notas", models.TextField(blank=True, null=True)),
                (
                    "solicitud",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="articulos",
                        to="solicitudes.solicitud",
                    ),
                ),
            ],
            options={
                "verbose_name": "artículo de solicitud",
                "verbose_name_plural": "artículos de solicitudes",
                "db_table": "articulos_solicitud",
                "ordering": ("creado_en", "id"),
                "indexes": [
                    models.Index(
                        fields=["solicitud", "creado_en"],
                        name="art_sol_solicitud_creado_idx",
                    )
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(cantidad__gt=0),
                        name="articulo_solicitud_cantidad_ck",
                    )
                ],
            },
        ),
        migrations.AddIndex(
            model_name="solicitud",
            index=models.Index(
                fields=["empresa", "-creado_en"],
                name="solicitud_emp_creado_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="solicitud",
            index=models.Index(
                fields=["estado", "-creado_en"],
                name="solicitud_est_creado_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="solicitud",
            index=models.Index(
                fields=["solicitada_por", "-creado_en"],
                name="solicitud_usr_creado_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="solicitud",
            constraint=models.CheckConstraint(
                condition=models.Q(prioridad__in=["NORMAL", "PRIORITY"]),
                name="solicitud_prioridad_valida_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="solicitud",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    estado__in=[
                        "PENDING",
                        "ASSIGNED",
                        "GOING_TO_PICKUP",
                        "AT_PICKUP",
                        "PICKED_UP",
                        "IN_TRANSIT",
                        "AT_DESTINATION",
                        "DELIVERED",
                        "CANCELLED",
                        "PICKUP_FAILED",
                        "DELIVERY_FAILED",
                    ]
                ),
                name="solicitud_estado_valido_ck",
            ),
        ),
    ]
