from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.jornadas.opciones import EstadoJornada
from apps.nucleo.models import ModeloUUIDConMarcasDeTiempo


class JornadaRepartidor(ModeloUUIDConMarcasDeTiempo):
    repartidor = models.ForeignKey(
        "repartidores.Repartidor",
        on_delete=models.PROTECT,
        related_name="jornadas",
    )
    estado = models.CharField(
        max_length=16,
        choices=EstadoJornada.choices,
        default=EstadoJornada.ACTIVA,
    )
    iniciada_en = models.DateTimeField(default=timezone.now)
    fecha_operativa = models.DateField(null=True, blank=True, editable=False)
    cierre_programado_en = models.DateTimeField(null=True, blank=True, editable=False)
    finalizada_en = models.DateTimeField(null=True, blank=True)
    latitud_inicio = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    longitud_inicio = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    latitud_fin = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    longitud_fin = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    kilometros_operativos = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    kilometraje_disponible = models.BooleanField(default=False)
    calidad_kilometraje = models.JSONField(default=dict, blank=True)
    minutos_operativos = models.PositiveIntegerField(null=True, blank=True)
    servicios_completados = models.PositiveIntegerField(default=0)
    recolecciones_completadas = models.PositiveIntegerField(default=0)
    entregas_completadas = models.PositiveIntegerField(default=0)
    servicios_normales = models.PositiveIntegerField(default=0)
    servicios_prioritarios = models.PositiveIntegerField(default=0)
    minutos_activos = models.PositiveIntegerField(default=0)
    incidencias_reportadas = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "jornadas_repartidor"
        ordering = ("-iniciada_en", "-id")
        indexes = [
            models.Index(
                fields=("repartidor", "-iniciada_en"),
                name="jornada_repart_fecha_idx",
            ),
            models.Index(
                fields=("estado", "-iniciada_en"),
                name="jornada_estado_fecha_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("repartidor", "fecha_operativa"),
                condition=models.Q(fecha_operativa__isnull=False),
                name="jornada_repart_dia_uniq",
            ),
            models.UniqueConstraint(
                fields=("repartidor",),
                condition=models.Q(estado=EstadoJornada.ACTIVA),
                name="jornada_repart_activa_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        estado=EstadoJornada.ACTIVA,
                        finalizada_en__isnull=True,
                    )
                    | models.Q(
                        estado=EstadoJornada.FINALIZADA,
                        finalizada_en__isnull=False,
                    )
                ),
                name="jornada_cierre_valido_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        latitud_inicio__isnull=True,
                        longitud_inicio__isnull=True,
                    )
                    | models.Q(
                        latitud_inicio__gte=-90,
                        latitud_inicio__lte=90,
                        longitud_inicio__gte=-180,
                        longitud_inicio__lte=180,
                    )
                ),
                name="jornada_gps_inicio_valido_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        latitud_fin__isnull=True,
                        longitud_fin__isnull=True,
                    )
                    | models.Q(
                        latitud_fin__gte=-90,
                        latitud_fin__lte=90,
                        longitud_fin__gte=-180,
                        longitud_fin__lte=180,
                    )
                ),
                name="jornada_gps_fin_valido_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(kilometros_operativos__gte=0),
                name="jornada_km_no_negativos_ck",
            ),
        ]
        verbose_name = "jornada de motorista"
        verbose_name_plural = "jornadas de motoristas"

    def __str__(self):
        return f"{self.repartidor} - {self.iniciada_en:%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        if self._state.adding and self.estado == EstadoJornada.ACTIVA:
            from apps.jornadas.horario import corte_operativo, periodo_operativo

            empresa = self.repartidor.empresa
            if self.fecha_operativa is None:
                self.fecha_operativa = periodo_operativo(self.iniciada_en, empresa)[0]
            if self.cierre_programado_en is None:
                self.cierre_programado_en = corte_operativo(self.iniciada_en, empresa)
        super().save(*args, **kwargs)


class AlmuerzoJornada(ModeloUUIDConMarcasDeTiempo):
    jornada = models.ForeignKey(JornadaRepartidor, on_delete=models.PROTECT, related_name="almuerzos")
    iniciada_en = models.DateTimeField(default=timezone.now)
    finalizada_en = models.DateTimeField(null=True, blank=True)
    finalizada_por = models.ForeignKey("usuarios.Usuario", on_delete=models.PROTECT, null=True, blank=True)
    motivo_cierre = models.CharField(max_length=32, blank=True, default="")

    class Meta:
        db_table = "almuerzos_jornada"
        ordering = ("iniciada_en", "id")
        constraints = [
            models.UniqueConstraint(fields=("jornada",), condition=models.Q(finalizada_en__isnull=True), name="almuerzo_jornada_activo_uniq"),
            models.CheckConstraint(condition=models.Q(finalizada_en__isnull=True) | models.Q(finalizada_en__gte=models.F("iniciada_en")), name="almuerzo_fechas_validas_ck"),
        ]
