from django.core.exceptions import ValidationError
from django.db import models
from apps.geografia.normalizacion import clave_departamento, nombre_departamento

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
    limite_tubos = models.PositiveIntegerField(default=20)
    pais_operacion = models.ForeignKey("geografia.Pais", on_delete=models.PROTECT, null=True, blank=True, related_name="motoristas_operativos")
    departamento_operacion = models.CharField(max_length=150, blank=True, default="")
    departamento_operacion_clave = models.CharField(max_length=150, blank=True, default="", editable=False)

    @property
    def cobertura_configurada(self):
        return bool(self.pais_operacion_id and self.departamento_operacion_clave)

    class Meta:
        db_table = "repartidores"
        ordering = ("usuario__nombres", "usuario__apellidos", "id")
        indexes = [
            models.Index(fields=("pais_operacion", "departamento_operacion_clave", "activo"), name="repart_pais_depto_act_idx"),
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
            models.CheckConstraint(condition=(
                models.Q(pais_operacion__isnull=True, departamento_operacion="", departamento_operacion_clave="")
                | (models.Q(pais_operacion__isnull=False) & ~models.Q(departamento_operacion="") & ~models.Q(departamento_operacion_clave=""))
            ), name="repart_cobertura_pareja_ck"),
            models.CheckConstraint(condition=models.Q(limite_tubos__gte=1), name="repart_limite_tubos_ck"),
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
        self.departamento_operacion = nombre_departamento(self.departamento_operacion)
        self.departamento_operacion_clave = clave_departamento(self.departamento_operacion)
        if len(self.departamento_operacion_clave) > 150:
            errores["departamento_operacion"] = "El departamento normalizado supera la longitud permitida."
        if bool(self.pais_operacion_id) != bool(self.departamento_operacion):
            errores["departamento_operacion"] = "Debe indicar conjuntamente país y departamento de operación."
        if self.empresa_id and self.pais_operacion_id and self.empresa.pais_id != self.pais_operacion_id:
            errores["pais_operacion"] = "El país de operación debe coincidir con el país de la empresa."
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
        if kwargs.get("update_fields") and "departamento_operacion" in kwargs["update_fields"]:
            kwargs["update_fields"] = (*kwargs["update_fields"], "departamento_operacion_clave")
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.usuario.get_full_name() or self.usuario.correo


class HistorialEstadoRepartidor(ModeloUUIDConMarcasDeTiempo):
    datos_adicionales = models.JSONField(default=dict, blank=True)
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
        null=True,
        blank=True,
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
