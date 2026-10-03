from django.core.exceptions import ValidationError
from django.db import models

from apps.nucleo.models import ModeloUUIDConMarcasDeTiempo
from apps.repartidores.opciones import (
    CapacidadRepartidor,
    EstadoOperativoRepartidor,
)


class Repartidor(ModeloUUIDConMarcasDeTiempo):
    usuario = models.OneToOneField(
        "usuarios.Usuario",
        on_delete=models.PROTECT,
        related_name="perfil_repartidor",
    )
    empresa = models.ForeignKey(
        "organizaciones.Empresa",
        on_delete=models.PROTECT,
        related_name="repartidores",
        null=True,
        blank=True,
    )
    vehiculo = models.ForeignKey(
        "flota.Vehiculo",
        on_delete=models.PROTECT,
        related_name="repartidores",
        null=True,
        blank=True,
    )
    estado_operativo = models.CharField(
        max_length=20,
        choices=EstadoOperativoRepartidor.choices,
        default=EstadoOperativoRepartidor.DESCONECTADO,
    )
    capacidad = models.CharField(
        max_length=20,
        choices=CapacidadRepartidor.choices,
        default=CapacidadRepartidor.VACIO,
    )
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "repartidores"
        ordering = ("usuario__nombres", "usuario__apellidos", "id")
        indexes = [
            models.Index(
                fields=("empresa", "activo", "estado_operativo"),
                name="repart_emp_act_est_idx",
            ),
            models.Index(
                fields=("estado_operativo", "capacidad"),
                name="repart_estado_cap_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    estado_operativo__in=EstadoOperativoRepartidor.values
                ),
                name="repart_estado_valido_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(capacidad__in=CapacidadRepartidor.values),
                name="repart_capacidad_valida_ck",
            ),
        ]
        verbose_name = "motorista"
        verbose_name_plural = "motoristas"

    def clean(self):
        super().clean()
        errores = {}
        if self.usuario_id and self.empresa_id:
            if self.usuario.empresa_id != self.empresa_id:
                errores["usuario"] = (
                    "El usuario debe pertenecer a la empresa del motorista."
                )
        if self.vehiculo_id:
            if self.vehiculo.empresa_id != self.empresa_id:
                errores["vehiculo"] = (
                    "El vehículo debe pertenecer al mismo alcance del motorista."
                )
        if errores:
            raise ValidationError(errores)

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.usuario.get_full_name() or self.usuario.correo


class HistorialEstadoRepartidor(ModeloUUIDConMarcasDeTiempo):
    repartidor = models.ForeignKey(
        Repartidor,
        on_delete=models.PROTECT,
        related_name="historial_operativo",
    )
    estado_anterior = models.CharField(
        max_length=20,
        choices=EstadoOperativoRepartidor.choices,
    )
    estado_nuevo = models.CharField(
        max_length=20,
        choices=EstadoOperativoRepartidor.choices,
    )
    capacidad_anterior = models.CharField(
        max_length=20,
        choices=CapacidadRepartidor.choices,
    )
    capacidad_nueva = models.CharField(
        max_length=20,
        choices=CapacidadRepartidor.choices,
    )
    realizado_por = models.ForeignKey(
        "usuarios.Usuario",
        on_delete=models.PROTECT,
        related_name="cambios_operativos_repartidores",
    )
    motivo = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "historial_estado_repartidor"
        ordering = ("-creado_en", "-id")
        indexes = [
            models.Index(
                fields=("repartidor", "-creado_en"),
                name="hist_repart_fecha_idx",
            ),
        ]
        verbose_name = "cambio operativo de motorista"
        verbose_name_plural = "cambios operativos de motoristas"

    def __str__(self):
        return f"{self.repartidor_id}: {self.estado_anterior} → {self.estado_nuevo}"
