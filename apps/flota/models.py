from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from apps.flota.opciones import EstadoVehiculo, TipoVehiculo
from apps.nucleo.models import ModeloUUIDConMarcasDeTiempo


class Vehiculo(ModeloUUIDConMarcasDeTiempo):
    empresa = models.ForeignKey(
        "organizaciones.Empresa",
        on_delete=models.PROTECT,
        related_name="vehiculos",
        null=True,
        blank=True,
    )
    placa = models.CharField(max_length=32, unique=True)
    tipo = models.CharField(max_length=20, choices=TipoVehiculo.choices)
    marca = models.CharField(max_length=80, null=True, blank=True)
    modelo = models.CharField(max_length=80, null=True, blank=True)
    anio = models.PositiveSmallIntegerField(null=True, blank=True)
    capacidad_carga_kg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    estado = models.CharField(
        max_length=20,
        choices=EstadoVehiculo.choices,
        default=EstadoVehiculo.ACTIVO,
    )
    notas = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "vehiculos"
        ordering = ("placa", "id")
        indexes = [
            models.Index(
                fields=("empresa", "estado"),
                name="vehiculo_emp_estado_idx",
            ),
            models.Index(fields=("estado",), name="vehiculo_estado_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(tipo__in=TipoVehiculo.values),
                name="vehiculo_tipo_valido_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(estado__in=EstadoVehiculo.values),
                name="vehiculo_estado_valido_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(capacidad_carga_kg__isnull=True)
                    | models.Q(capacidad_carga_kg__gt=0)
                ),
                name="vehiculo_capacidad_positiva_ck",
            ),
        ]
        verbose_name = "vehículo"
        verbose_name_plural = "vehículos"

    def clean(self):
        super().clean()
        self.placa = self.placa.strip().upper()

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.placa
