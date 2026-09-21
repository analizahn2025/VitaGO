from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.nucleo.models import ModeloUUID, ModeloUUIDConMarcasDeTiempo
from apps.ubicaciones.opciones import (
    EstadoUbicacion,
    EstadoUbicacionEmpresa,
    OrigenUbicacion,
)


class TipoUbicacion(ModeloUUID):
    codigo = models.CharField(max_length=64, unique=True)
    nombre = models.CharField(max_length=150)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "tipos_ubicacion"
        ordering = ("nombre",)
        verbose_name = "tipo de ubicación"
        verbose_name_plural = "tipos de ubicación"

    def clean(self):
        super().clean()
        self.codigo = self.codigo.strip().upper()

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.nombre


class Ubicacion(ModeloUUIDConMarcasDeTiempo):
    nombre = models.CharField(max_length=200)
    tipo_ubicacion = models.ForeignKey(
        TipoUbicacion,
        on_delete=models.PROTECT,
        related_name="ubicaciones",
    )
    origen = models.CharField(max_length=24, choices=OrigenUbicacion.choices)
    identificador_lugar_google = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )
    pais = models.ForeignKey(
        "geografia.Pais",
        on_delete=models.PROTECT,
        related_name="ubicaciones",
    )
    nivel_administrativo_1 = models.CharField(
        max_length=150,
        null=True,
        blank=True,
    )
    nivel_administrativo_2 = models.CharField(
        max_length=150,
        null=True,
        blank=True,
    )
    localidad = models.CharField(max_length=150, null=True, blank=True)
    direccion = models.TextField()
    latitud = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        validators=[
            MinValueValidator(Decimal("-90")),
            MaxValueValidator(Decimal("90")),
        ],
    )
    longitud = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        validators=[
            MinValueValidator(Decimal("-180")),
            MaxValueValidator(Decimal("180")),
        ],
    )
    telefono = models.CharField(max_length=32, null=True, blank=True)
    nombre_contacto = models.CharField(max_length=200, null=True, blank=True)
    horario_atencion = models.JSONField(null=True, blank=True)
    instrucciones = models.TextField(null=True, blank=True)
    verificada = models.BooleanField(default=False)
    estado = models.CharField(
        max_length=16,
        choices=EstadoUbicacion.choices,
        default=EstadoUbicacion.ACTIVO,
    )
    creada_por = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "ubicaciones"
        ordering = ("nombre",)
        indexes = [
            models.Index(
                fields=("pais", "estado"),
                name="ubicaciones_pais_estado_idx",
            ),
            models.Index(
                fields=("identificador_lugar_google",),
                name="ubicaciones_google_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(latitud__gte=-90, latitud__lte=90),
                name="ubicaciones_latitud_rango_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(longitud__gte=-180, longitud__lte=180),
                name="ubicaciones_longitud_rango_ck",
            ),
        ]
        verbose_name = "ubicación"
        verbose_name_plural = "ubicaciones"

    def __str__(self):
        return self.nombre


class UbicacionEmpresa(ModeloUUIDConMarcasDeTiempo):
    empresa = models.ForeignKey(
        "organizaciones.Empresa",
        on_delete=models.PROTECT,
        related_name="ubicaciones_autorizadas",
    )
    ubicacion = models.ForeignKey(
        Ubicacion,
        on_delete=models.PROTECT,
        related_name="empresas_autorizadas",
    )
    permite_origen = models.BooleanField(default=False)
    permite_destino = models.BooleanField(default=False)
    estado = models.CharField(
        max_length=16,
        choices=EstadoUbicacionEmpresa.choices,
        default=EstadoUbicacionEmpresa.PENDIENTE,
    )

    class Meta:
        db_table = "ubicaciones_empresa"
        ordering = ("empresa_id", "ubicacion_id")
        constraints = [
            models.UniqueConstraint(
                fields=("empresa", "ubicacion"),
                name="ubic_empresa_relacion_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=("empresa", "estado"),
                name="ubic_empresa_estado_idx",
            ),
        ]
        verbose_name = "ubicación autorizada para empresa"
        verbose_name_plural = "ubicaciones autorizadas para empresas"

    def __str__(self):
        return f"{self.empresa.nombre} - {self.ubicacion.nombre}"
