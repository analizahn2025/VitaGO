from django.db import models

from apps.evidencias.opciones import TipoEvidenciaSolicitud
from apps.nucleo.models import ModeloUUIDConMarcasDeTiempo


class EvidenciaSolicitud(ModeloUUIDConMarcasDeTiempo):
    solicitud = models.ForeignKey(
        "solicitudes.Solicitud",
        on_delete=models.PROTECT,
        related_name="evidencias",
    )
    repartidor = models.ForeignKey(
        "repartidores.Repartidor",
        on_delete=models.PROTECT,
        related_name="evidencias_solicitudes",
    )
    tipo = models.CharField(
        max_length=24,
        choices=TipoEvidenciaSolicitud.choices,
    )
    clave_almacenamiento = models.CharField(max_length=500, unique=True)
    url_archivo = models.URLField(max_length=1000, null=True, blank=True)
    tipo_contenido = models.CharField(max_length=100)
    tamano_bytes = models.PositiveBigIntegerField()
    latitud = models.DecimalField(max_digits=9, decimal_places=6)
    longitud = models.DecimalField(max_digits=9, decimal_places=6)
    capturada_en = models.DateTimeField()
    notas = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "evidencias_solicitud"
        ordering = ("capturada_en", "id")
        indexes = [
            models.Index(
                fields=("solicitud", "tipo", "-capturada_en"),
                name="evid_sol_tipo_fecha_idx",
            ),
            models.Index(
                fields=("repartidor", "-capturada_en"),
                name="evid_repart_fecha_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(tipo__in=TipoEvidenciaSolicitud.values),
                name="evidencia_tipo_valido_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(latitud__gte=-90, latitud__lte=90),
                name="evidencia_latitud_valida_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(longitud__gte=-180, longitud__lte=180),
                name="evidencia_longitud_valida_ck",
            ),
        ]
        verbose_name = "evidencia de solicitud"
        verbose_name_plural = "evidencias de solicitudes"

    def __str__(self):
        return f"{self.solicitud.numero} - {self.get_tipo_display()}"

