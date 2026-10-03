from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.nucleo.models import ModeloUUIDConMarcasDeTiempo


class RegistroUbicacion(ModeloUUIDConMarcasDeTiempo):
    id_cliente = models.UUIDField()
    repartidor = models.ForeignKey(
        "repartidores.Repartidor",
        on_delete=models.PROTECT,
        related_name="registros_ubicacion",
    )
    jornada = models.ForeignKey(
        "jornadas.JornadaRepartidor",
        on_delete=models.PROTECT,
        related_name="registros_ubicacion",
    )
    movimiento_envio_especial = models.ForeignKey(
        "solicitudes.MovimientoEnvioEspecial",
        on_delete=models.PROTECT,
        related_name="registros_ubicacion",
        null=True,
        blank=True,
    )
    latitud = models.DecimalField(max_digits=9, decimal_places=6)
    longitud = models.DecimalField(max_digits=9, decimal_places=6)
    precision_metros = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    velocidad_metros_segundo = models.DecimalField(
        max_digits=8,
        decimal_places=3,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    rumbo_grados = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("0")),
            MaxValueValidator(Decimal("359.99")),
        ],
    )
    registrada_en = models.DateTimeField()
    es_operativo = models.BooleanField(default=False)

    class Meta:
        db_table = "registros_ubicacion"
        ordering = ("-registrada_en", "-id")
        indexes = [
            models.Index(
                fields=("repartidor", "-registrada_en"),
                name="reg_ubi_repart_fecha_idx",
            ),
            models.Index(
                fields=("jornada", "-registrada_en"),
                name="reg_ubi_jornada_fecha_idx",
            ),
            models.Index(
                fields=("repartidor", "es_operativo", "-registrada_en"),
                name="reg_ubi_repart_op_fecha_idx",
            ),
            models.Index(
                fields=("movimiento_envio_especial", "registrada_en"),
                name="reg_ubi_mov_esp_fecha_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("repartidor", "id_cliente"),
                name="reg_ubi_repart_cliente_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    latitud__gte=-90,
                    latitud__lte=90,
                    longitud__gte=-180,
                    longitud__lte=180,
                ),
                name="reg_ubi_coordenadas_validas_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(precision_metros__isnull=True)
                    | models.Q(precision_metros__gte=0)
                ),
                name="reg_ubi_precision_valida_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(velocidad_metros_segundo__isnull=True)
                    | models.Q(velocidad_metros_segundo__gte=0)
                ),
                name="reg_ubi_velocidad_valida_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(rumbo_grados__isnull=True)
                    | models.Q(
                        rumbo_grados__gte=0,
                        rumbo_grados__lt=360,
                    )
                ),
                name="reg_ubi_rumbo_valido_ck",
            ),
        ]
        verbose_name = "registro de ubicación"
        verbose_name_plural = "registros de ubicación"

    def __str__(self):
        return f"{self.repartidor_id} - {self.registrada_en:%Y-%m-%d %H:%M:%S}"
