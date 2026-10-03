from django.db import models

from apps.incidencias.opciones import EstadoIncidencia, TipoEventoIncidencia
from apps.nucleo.models import ModeloUUIDConMarcasDeTiempo


class Incidencia(ModeloUUIDConMarcasDeTiempo):
    jornada = models.ForeignKey(
        "jornadas.JornadaRepartidor",
        on_delete=models.PROTECT,
        related_name="incidencias",
    )
    repartidor = models.ForeignKey(
        "repartidores.Repartidor",
        on_delete=models.PROTECT,
        related_name="incidencias",
    )
    solicitud = models.ForeignKey(
        "solicitudes.Solicitud",
        on_delete=models.PROTECT,
        related_name="incidencias",
        null=True,
        blank=True,
    )
    estado = models.CharField(
        max_length=16,
        choices=EstadoIncidencia.choices,
        default=EstadoIncidencia.ABIERTA,
    )
    descripcion = models.TextField()
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
    reportada_en = models.DateTimeField()
    revisada_por = models.ForeignKey(
        "usuarios.Usuario",
        on_delete=models.PROTECT,
        related_name="incidencias_revisadas",
        null=True,
        blank=True,
    )
    revisada_en = models.DateTimeField(null=True, blank=True)
    cerrada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "incidencias"
        ordering = ("-reportada_en", "-id")
        indexes = [
            models.Index(
                fields=("repartidor", "-reportada_en"),
                name="inc_repart_fecha_idx",
            ),
            models.Index(
                fields=("jornada", "estado"),
                name="inc_jornada_estado_idx",
            ),
            models.Index(
                fields=("solicitud", "-reportada_en"),
                name="inc_solic_fecha_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(estado__in=EstadoIncidencia.values),
                name="inc_estado_valido_ck",
            ),
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
                name="inc_coordenadas_validas_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        estado=EstadoIncidencia.ABIERTA,
                        revisada_por__isnull=True,
                        revisada_en__isnull=True,
                        cerrada_en__isnull=True,
                    )
                    | models.Q(
                        estado=EstadoIncidencia.EN_REVISION,
                        revisada_por__isnull=False,
                        revisada_en__isnull=False,
                        cerrada_en__isnull=True,
                    )
                    | models.Q(
                        estado=EstadoIncidencia.CERRADA,
                        revisada_por__isnull=False,
                        revisada_en__isnull=False,
                        cerrada_en__isnull=False,
                    )
                ),
                name="inc_revision_consistente_ck",
            ),
        ]
        verbose_name = "incidencia"
        verbose_name_plural = "incidencias"

    def __str__(self):
        return f"{self.repartidor_id} - {self.reportada_en:%Y-%m-%d %H:%M}"


class EventoIncidencia(ModeloUUIDConMarcasDeTiempo):
    incidencia = models.ForeignKey(
        Incidencia,
        on_delete=models.PROTECT,
        related_name="eventos",
    )
    tipo = models.CharField(max_length=24, choices=TipoEventoIncidencia.choices)
    realizado_por = models.ForeignKey(
        "usuarios.Usuario",
        on_delete=models.PROTECT,
        related_name="eventos_incidencias_realizados",
    )
    estado_anterior = models.CharField(
        max_length=16,
        choices=EstadoIncidencia.choices,
        null=True,
        blank=True,
    )
    estado_nuevo = models.CharField(
        max_length=16,
        choices=EstadoIncidencia.choices,
        null=True,
        blank=True,
    )
    notas = models.TextField(null=True, blank=True)
    metadatos = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "eventos_incidencia"
        ordering = ("creado_en", "id")
        indexes = [
            models.Index(
                fields=("incidencia", "creado_en"),
                name="evt_inc_incid_fecha_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(tipo__in=TipoEventoIncidencia.values),
                name="evt_inc_tipo_valido_ck",
            ),
        ]
        verbose_name = "evento de incidencia"
        verbose_name_plural = "eventos de incidencias"


class EvidenciaIncidencia(ModeloUUIDConMarcasDeTiempo):
    incidencia = models.ForeignKey(
        Incidencia,
        on_delete=models.PROTECT,
        related_name="evidencias",
    )
    repartidor = models.ForeignKey(
        "repartidores.Repartidor",
        on_delete=models.PROTECT,
        related_name="evidencias_incidencias",
    )
    clave_almacenamiento = models.CharField(max_length=500, unique=True)
    tipo_contenido = models.CharField(max_length=100)
    tamano_bytes = models.PositiveBigIntegerField()
    latitud = models.DecimalField(max_digits=9, decimal_places=6)
    longitud = models.DecimalField(max_digits=9, decimal_places=6)
    capturada_en = models.DateTimeField()
    notas = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "evidencias_incidencia"
        ordering = ("capturada_en", "id")
        indexes = [
            models.Index(
                fields=("incidencia", "-capturada_en"),
                name="evid_inc_incid_fecha_idx",
            ),
            models.Index(
                fields=("repartidor", "-capturada_en"),
                name="evid_inc_repart_fecha_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(latitud__gte=-90, latitud__lte=90),
                name="evid_inc_latitud_valida_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(longitud__gte=-180, longitud__lte=180),
                name="evid_inc_longitud_valida_ck",
            ),
        ]
        verbose_name = "evidencia de incidencia"
        verbose_name_plural = "evidencias de incidencias"

