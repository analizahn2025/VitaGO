from django.db import models

from apps.nucleo.models import ModeloConMarcasDeTiempo, ModeloUUIDConMarcasDeTiempo
from apps.organizaciones.opciones import EstadoOrganizacion


class Empresa(ModeloUUIDConMarcasDeTiempo):
    nombre = models.CharField(max_length=200)
    limite_tubos_por_motorista = models.PositiveIntegerField(default=20)
    limite_solicitudes_por_motorista = models.PositiveSmallIntegerField(default=5)
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
        constraints = [
            models.CheckConstraint(
                condition=models.Q(limite_tubos_por_motorista__gte=1),
                name="empresa_limite_tubos_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(limite_solicitudes_por_motorista__gte=1, limite_solicitudes_por_motorista__lte=5),
                name="empresa_limite_solicitudes_ck",
            ),
        ]

    def __str__(self):
        return self.nombre


class LimitesMotoristasRed(ModeloConMarcasDeTiempo):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    limite_tubos_por_motorista = models.PositiveIntegerField(default=20)
    limite_solicitudes_por_motorista = models.PositiveSmallIntegerField(default=5)

    class Meta:
        db_table = "limites_motoristas_red"
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name="limites_red_unica_fila_ck"),
            models.CheckConstraint(condition=models.Q(limite_tubos_por_motorista__gte=1), name="limites_red_tubos_ck"),
            models.CheckConstraint(
                condition=models.Q(limite_solicitudes_por_motorista__gte=1, limite_solicitudes_por_motorista__lte=5),
                name="limites_red_solicitudes_ck",
            ),
        ]


class HistorialLimitesMotoristas(ModeloUUIDConMarcasDeTiempo):
    # Sin empresa representa la configuración general de Network.
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="historial_limites", null=True, blank=True,
    )
    realizado_por = models.ForeignKey(
        "usuarios.Usuario", on_delete=models.PROTECT, related_name="cambios_limites_motoristas",
    )
    limites_anteriores = models.JSONField()
    limites_nuevos = models.JSONField()
    motivo = models.CharField(max_length=1000, blank=True, default="")

    class Meta:
        db_table = "historial_limites_motoristas"
        ordering = ("-creado_en", "-id")


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
