from django.db import models

from apps.nucleo.models import ModeloUUIDConMarcasDeTiempo
from apps.organizaciones.opciones import EstadoOrganizacion


class Empresa(ModeloUUIDConMarcasDeTiempo):
    nombre = models.CharField(max_length=200)
    razon_social = models.CharField(max_length=250, null=True, blank=True)
    identificacion_fiscal = models.CharField(max_length=64, null=True, blank=True)
    telefono = models.CharField(max_length=32, null=True, blank=True)
    correo = models.EmailField(null=True, blank=True)
    pais = models.ForeignKey(
        "geografia.Pais",
        on_delete=models.PROTECT,
        related_name="empresas",
    )
    estado = models.CharField(
        max_length=16,
        choices=EstadoOrganizacion.choices,
        default=EstadoOrganizacion.ACTIVO,
    )

    class Meta:
        db_table = "empresas"
        ordering = ("nombre",)
        indexes = [
            models.Index(
                fields=("pais", "estado"),
                name="empresas_pais_estado_idx",
            ),
            models.Index(fields=("estado",), name="empresas_estado_idx"),
        ]
        verbose_name = "empresa"
        verbose_name_plural = "empresas"

    def __str__(self):
        return self.nombre


class Sucursal(ModeloUUIDConMarcasDeTiempo):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.PROTECT,
        related_name="sucursales",
    )
    nombre = models.CharField(max_length=200)
    codigo = models.CharField(max_length=64, null=True, blank=True)
    ubicacion = models.ForeignKey(
        "ubicaciones.Ubicacion",
        on_delete=models.PROTECT,
        related_name="sucursales",
    )
    telefono = models.CharField(max_length=32, null=True, blank=True)
    correo = models.EmailField(null=True, blank=True)
    estado = models.CharField(
        max_length=16,
        choices=EstadoOrganizacion.choices,
        default=EstadoOrganizacion.ACTIVO,
    )

    class Meta:
        db_table = "sucursales"
        ordering = ("empresa_id", "nombre")
        indexes = [
            models.Index(
                fields=("empresa", "estado"),
                name="sucursales_empresa_estado_idx",
            ),
        ]
        verbose_name = "sucursal"
        verbose_name_plural = "sucursales"

    def __str__(self):
        return f"{self.empresa.nombre} - {self.nombre}"
