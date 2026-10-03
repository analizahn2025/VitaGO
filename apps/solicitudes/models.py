from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.nucleo.models import ModeloUUID, ModeloUUIDConMarcasDeTiempo
from apps.solicitudes.opciones import (
    EstadoAsignacionSolicitud,
    EstadoMovimientoEnvioEspecial,
    EstadoSolicitud,
    ModalidadSolicitud,
    PrioridadSolicitud,
    TipoAsignacionSolicitud,
    TipoEventoSolicitud,
)


class TipoServicio(ModeloUUID):
    codigo = models.CharField(max_length=64, unique=True)
    nombre = models.CharField(max_length=150)
    descripcion = models.TextField(null=True, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "tipos_servicio"
        ordering = ("nombre", "id")
        verbose_name = "tipo de servicio"
        verbose_name_plural = "tipos de servicio"

    def clean(self):
        super().clean()
        self.codigo = self.codigo.strip().upper()

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.nombre


class Solicitud(ModeloUUIDConMarcasDeTiempo):
    numero = models.CharField(max_length=32, unique=True)
    empresa = models.ForeignKey(
        "organizaciones.Empresa",
        on_delete=models.PROTECT,
        related_name="solicitudes",
    )
    sucursal = models.ForeignKey(
        "organizaciones.Sucursal",
        on_delete=models.PROTECT,
        related_name="solicitudes",
        null=True,
        blank=True,
    )
    solicitada_por = models.ForeignKey(
        "usuarios.Usuario",
        on_delete=models.PROTECT,
        related_name="solicitudes_creadas",
    )
    repartidor_asignado = models.ForeignKey(
        "repartidores.Repartidor",
        on_delete=models.PROTECT,
        related_name="solicitudes_asignadas",
        null=True,
        blank=True,
    )
    prioridad = models.CharField(
        max_length=16,
        choices=PrioridadSolicitud.choices,
    )
    modalidad = models.CharField(
        max_length=32,
        choices=ModalidadSolicitud.choices,
        null=True,
        blank=True,
    )
    tipo_servicio = models.ForeignKey(
        TipoServicio,
        on_delete=models.PROTECT,
        related_name="solicitudes",
        null=True,
        blank=True,
    )
    origen = models.ForeignKey(
        "ubicaciones.Ubicacion",
        on_delete=models.PROTECT,
        related_name="solicitudes_como_origen",
    )
    destino = models.ForeignKey(
        "ubicaciones.Ubicacion",
        on_delete=models.PROTECT,
        related_name="solicitudes_como_destino",
        null=True,
        blank=True,
    )
    destino_especial = models.TextField(null=True, blank=True)
    estado = models.CharField(
        max_length=24,
        choices=EstadoSolicitud.choices,
        default=EstadoSolicitud.PENDIENTE,
    )
    notas = models.TextField(null=True, blank=True)
    asignada_en = models.DateTimeField(null=True, blank=True)
    llegada_recoleccion_en = models.DateTimeField(null=True, blank=True)
    recolectada_en = models.DateTimeField(null=True, blank=True)
    llegada_destino_en = models.DateTimeField(null=True, blank=True)
    entregada_en = models.DateTimeField(null=True, blank=True)
    cancelada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "solicitudes"
        ordering = ("-creado_en", "-id")
        indexes = [
            models.Index(
                fields=("empresa", "-creado_en"),
                name="solicitud_emp_creado_idx",
            ),
            models.Index(
                fields=("estado", "-creado_en"),
                name="solicitud_est_creado_idx",
            ),
            models.Index(
                fields=("solicitada_por", "-creado_en"),
                name="solicitud_usr_creado_idx",
            ),
            models.Index(
                fields=("repartidor_asignado", "estado"),
                name="solicitud_repart_est_idx",
            ),
            models.Index(
                fields=("modalidad", "estado", "-creado_en"),
                name="solicitud_modal_est_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    prioridad__in=PrioridadSolicitud.values,
                ),
                name="solicitud_prioridad_valida_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(estado__in=EstadoSolicitud.values),
                name="solicitud_estado_valido_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(modalidad__isnull=True, destino__isnull=False)
                    | models.Q(
                        modalidad=ModalidadSolicitud.ESPECIAL,
                        destino__isnull=True,
                        destino_especial__isnull=False,
                    )
                    | models.Q(
                        modalidad__in=(
                            ModalidadSolicitud.ABIERTO,
                            ModalidadSolicitud.ENTRE_SUCURSALES,
                            ModalidadSolicitud.EMPRESA_TRANSPORTE,
                        ),
                        destino__isnull=False,
                        destino_especial__isnull=True,
                    )
                ),
                name="solicitud_destino_modalidad_ck",
            ),
        ]
        verbose_name = "solicitud"
        verbose_name_plural = "solicitudes"

    def clean(self):
        super().clean()
        if self.sucursal_id and self.empresa_id:
            if self.sucursal.empresa_id != self.empresa_id:
                raise ValidationError(
                    {
                        "sucursal": (
                            "La sucursal debe pertenecer a la empresa "
                            "de la solicitud."
                        )
                    }
                )
        if self.modalidad == ModalidadSolicitud.ESPECIAL:
            if self.destino_id is not None:
                raise ValidationError(
                    {"destino": "Un envío especial no usa un destino registrado."}
                )
            if not (self.destino_especial or "").strip():
                raise ValidationError(
                    {"destino_especial": "Debe describir el destino especial."}
                )
        elif self.destino_id is None:
            raise ValidationError(
                {"destino": "Esta modalidad requiere un destino registrado."}
            )
        elif self.destino_especial is not None:
            raise ValidationError(
                {"destino_especial": "Solo aplica a envíos especiales."}
            )

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.numero


class MovimientoEnvioEspecial(ModeloUUIDConMarcasDeTiempo):
    solicitud = models.OneToOneField(
        Solicitud,
        on_delete=models.PROTECT,
        related_name="movimiento_especial",
    )
    repartidor = models.ForeignKey(
        "repartidores.Repartidor",
        on_delete=models.PROTECT,
        related_name="movimientos_envios_especiales",
    )
    jornada = models.ForeignKey(
        "jornadas.JornadaRepartidor",
        on_delete=models.PROTECT,
        related_name="movimientos_envios_especiales",
    )
    estado = models.CharField(
        max_length=16,
        choices=EstadoMovimientoEnvioEspecial.choices,
        default=EstadoMovimientoEnvioEspecial.ACTIVO,
    )
    iniciada_en = models.DateTimeField()
    finalizada_en = models.DateTimeField(null=True, blank=True)
    latitud_inicio = models.DecimalField(max_digits=9, decimal_places=6)
    longitud_inicio = models.DecimalField(max_digits=9, decimal_places=6)
    latitud_fin = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitud_fin = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    kilometros_recorridos = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    registros_considerados = models.PositiveIntegerField(default=0)
    registros_descartados = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "movimientos_envios_especiales"
        ordering = ("-iniciada_en", "-id")
        indexes = [
            models.Index(
                fields=("repartidor", "estado", "-iniciada_en"),
                name="mov_esp_repart_est_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("repartidor",),
                condition=models.Q(estado=EstadoMovimientoEnvioEspecial.ACTIVO),
                name="mov_esp_repart_activo_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        estado=EstadoMovimientoEnvioEspecial.ACTIVO,
                        finalizada_en__isnull=True,
                        latitud_fin__isnull=True,
                        longitud_fin__isnull=True,
                    )
                    | models.Q(
                        estado=EstadoMovimientoEnvioEspecial.FINALIZADO,
                        finalizada_en__isnull=False,
                        latitud_fin__isnull=False,
                        longitud_fin__isnull=False,
                    )
                ),
                name="mov_esp_cierre_valido_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    latitud_inicio__gte=-90,
                    latitud_inicio__lte=90,
                    longitud_inicio__gte=-180,
                    longitud_inicio__lte=180,
                ),
                name="mov_esp_inicio_gps_ck",
            ),
            models.CheckConstraint(
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
            models.CheckConstraint(
                condition=models.Q(kilometros_recorridos__gte=0),
                name="mov_esp_km_no_negativos_ck",
            ),
        ]
        verbose_name = "movimiento de envío especial"
        verbose_name_plural = "movimientos de envíos especiales"

    def __str__(self):
        return f"{self.solicitud.numero} - {self.estado}"


class ArticuloSolicitud(ModeloUUIDConMarcasDeTiempo):
    solicitud = models.ForeignKey(
        Solicitud,
        on_delete=models.PROTECT,
        related_name="articulos",
    )
    tipo_articulo = models.CharField(max_length=100)
    descripcion = models.TextField(null=True, blank=True)
    cantidad = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("1"),
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    codigo_referencia = models.CharField(
        max_length=120,
        null=True,
        blank=True,
    )
    condicion_transporte = models.CharField(
        max_length=200,
        null=True,
        blank=True,
    )
    notas = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "articulos_solicitud"
        ordering = ("creado_en", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cantidad__gt=0),
                name="articulo_solicitud_cantidad_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=("solicitud", "creado_en"),
                name="art_sol_solicitud_creado_idx",
            ),
        ]
        verbose_name = "artículo de solicitud"
        verbose_name_plural = "artículos de solicitudes"

    def __str__(self):
        return f"{self.solicitud.numero} - {self.tipo_articulo}"


class EventoSolicitud(ModeloUUIDConMarcasDeTiempo):
    solicitud = models.ForeignKey(
        Solicitud,
        on_delete=models.PROTECT,
        related_name="eventos",
    )
    tipo = models.CharField(max_length=80, choices=TipoEventoSolicitud.choices)
    realizado_por = models.ForeignKey(
        "usuarios.Usuario",
        on_delete=models.PROTECT,
        related_name="eventos_solicitudes_realizados",
        null=True,
        blank=True,
    )
    repartidor = models.ForeignKey(
        "repartidores.Repartidor",
        on_delete=models.PROTECT,
        related_name="eventos_solicitudes",
        null=True,
        blank=True,
    )
    latitud = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    longitud = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    metadatos = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "eventos_solicitud"
        ordering = ("creado_en", "id")
        indexes = [
            models.Index(
                fields=("solicitud", "creado_en"),
                name="evt_sol_solic_creado_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(latitud__isnull=True, longitud__isnull=True)
                    | models.Q(
                        latitud__gte=-90,
                        latitud__lte=90,
                        longitud__gte=-180,
                        longitud__lte=180,
                    )
                ),
                name="evento_solicitud_gps_valido_ck",
            ),
        ]
        verbose_name = "evento de solicitud"
        verbose_name_plural = "eventos de solicitudes"

    def __str__(self):
        return f"{self.solicitud.numero} - {self.tipo}"


class AsignacionSolicitud(ModeloUUIDConMarcasDeTiempo):
    solicitud = models.ForeignKey(
        Solicitud,
        on_delete=models.PROTECT,
        related_name="asignaciones",
    )
    repartidor = models.ForeignKey(
        "repartidores.Repartidor",
        on_delete=models.PROTECT,
        related_name="asignaciones_solicitudes",
    )
    asignada_por = models.ForeignKey(
        "usuarios.Usuario",
        on_delete=models.PROTECT,
        related_name="asignaciones_solicitudes_realizadas",
    )
    tipo = models.CharField(
        max_length=16,
        choices=TipoAsignacionSolicitud.choices,
        default=TipoAsignacionSolicitud.MANUAL,
    )
    estado = models.CharField(
        max_length=16,
        choices=EstadoAsignacionSolicitud.choices,
        default=EstadoAsignacionSolicitud.ACTIVA,
    )
    asignada_en = models.DateTimeField(default=timezone.now)
    aceptada_en = models.DateTimeField(null=True, blank=True)
    finalizada_en = models.DateTimeField(null=True, blank=True)
    motivo = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "asignaciones_solicitud"
        ordering = ("-asignada_en", "-id")
        indexes = [
            models.Index(
                fields=("solicitud", "-asignada_en"),
                name="asig_sol_solic_fecha_idx",
            ),
            models.Index(
                fields=("repartidor", "estado"),
                name="asig_sol_repart_est_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("solicitud",),
                condition=models.Q(estado=EstadoAsignacionSolicitud.ACTIVA),
                name="asig_sol_activa_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(tipo__in=TipoAsignacionSolicitud.values),
                name="asig_sol_tipo_valido_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(estado__in=EstadoAsignacionSolicitud.values),
                name="asig_sol_estado_valido_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        estado=EstadoAsignacionSolicitud.ACTIVA,
                        finalizada_en__isnull=True,
                    )
                    | models.Q(
                        estado__in=(
                            EstadoAsignacionSolicitud.FINALIZADA,
                            EstadoAsignacionSolicitud.CANCELADA,
                            EstadoAsignacionSolicitud.REASIGNADA,
                        ),
                        finalizada_en__isnull=False,
                    )
                ),
                name="asig_sol_cierre_valido_ck",
            ),
        ]
        verbose_name = "asignación de solicitud"
        verbose_name_plural = "asignaciones de solicitudes"

    def __str__(self):
        return f"{self.solicitud.numero} - {self.repartidor_id}"
