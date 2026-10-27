"""Rutas operativas y versiones inmutables de sus paradas."""

from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.nucleo.models import ModeloUUIDConMarcasDeTiempo
from apps.solicitudes.opciones import EstadoSolicitud, ModalidadSolicitud, PrioridadSolicitud


class RutaRepartidor(ModeloUUIDConMarcasDeTiempo):
    class Estado(models.TextChoices):
        ACTIVA = "ACTIVA", "Activa"
        FINALIZADA = "FINALIZADA", "Finalizada"

    repartidor = models.ForeignKey(
        "repartidores.Repartidor", on_delete=models.PROTECT, related_name="rutas"
    )
    jornada = models.ForeignKey(
        "jornadas.JornadaRepartidor", on_delete=models.PROTECT,
        related_name="rutas", null=True, blank=True,
    )
    estado = models.CharField(
        max_length=16, choices=Estado.choices, default=Estado.ACTIVA
    )
    iniciada_en = models.DateTimeField(default=timezone.now)
    finalizada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "rutas_repartidor"
        ordering = ("-iniciada_en", "-id")
        indexes = [
            models.Index(fields=("repartidor", "-iniciada_en"), name="ruta_repart_fecha_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("repartidor",), condition=Q(estado="ACTIVA"),
                name="ruta_repart_activa_uniq",
            ),
            models.UniqueConstraint(
                fields=("jornada",), condition=Q(jornada__isnull=False),
                name="ruta_jornada_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(estado="ACTIVA", finalizada_en__isnull=True)
                    | Q(estado="FINALIZADA", finalizada_en__isnull=False)
                ), name="ruta_cierre_valido_ck",
            ),
        ]


class VersionRuta(ModeloUUIDConMarcasDeTiempo):
    class Motivo(models.TextChoices):
        INICIAL = "INICIAL", "Inicial"
        ASIGNACION = "ASIGNACION", "Asignación"
        REASIGNACION = "REASIGNACION", "Reasignación"
        CAMBIO_ESTADO = "CAMBIO_ESTADO", "Cambio de estado"
        CANCELACION = "CANCELACION", "Cancelación"
        INICIO_JORNADA = "INICIO_JORNADA", "Inicio de jornada"
        CIERRE_JORNADA = "CIERRE_JORNADA", "Cierre de jornada"

    ruta = models.ForeignKey(
        RutaRepartidor, on_delete=models.PROTECT, related_name="versiones"
    )
    numero = models.PositiveIntegerField()
    motivo = models.CharField(max_length=24, choices=Motivo.choices)
    creada_en = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "versiones_ruta"
        ordering = ("ruta", "numero")
        constraints = [
            models.UniqueConstraint(fields=("ruta", "numero"), name="version_ruta_numero_uniq"),
            models.CheckConstraint(condition=Q(numero__gte=1), name="version_ruta_numero_ck"),
        ]


class ParadaVersionRuta(ModeloUUIDConMarcasDeTiempo):
    class Tipo(models.TextChoices):
        RECOLECCION = "RECOLECCION", "Recolección"
        ENTREGA = "ENTREGA", "Entrega"
        ENVIO_ESPECIAL = "ENVIO_ESPECIAL", "Envío especial"

    version = models.ForeignKey(
        VersionRuta, on_delete=models.PROTECT, related_name="paradas"
    )
    solicitud = models.ForeignKey(
        "solicitudes.Solicitud", on_delete=models.PROTECT,
        related_name="paradas_versionadas",
    )
    orden = models.PositiveIntegerField()
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    numero_solicitud = models.CharField(max_length=32)
    prioridad = models.CharField(max_length=12, choices=PrioridadSolicitud.choices)
    modalidad = models.CharField(
        max_length=24, choices=ModalidadSolicitud.choices, null=True, blank=True
    )
    estado_solicitud = models.CharField(max_length=24, choices=EstadoSolicitud.choices)
    ubicacion = models.ForeignKey(
        "ubicaciones.Ubicacion", on_delete=models.PROTECT,
        null=True, blank=True, related_name="paradas_versionadas",
    )
    nombre_ubicacion = models.CharField(max_length=200, null=True, blank=True)
    direccion_ubicacion = models.TextField(null=True, blank=True)
    latitud_ubicacion = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitud_ubicacion = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    destino_especial = models.TextField(null=True, blank=True)
    presentacion_ruta = models.CharField(max_length=20)

    class Meta:
        db_table = "paradas_version_ruta"
        ordering = ("version", "orden")
        constraints = [
            models.UniqueConstraint(fields=("version", "orden"), name="parada_version_orden_uniq"),
            models.CheckConstraint(condition=Q(orden__gte=1), name="parada_version_orden_ck"),
        ]


class CalculoRutaVial(ModeloUUIDConMarcasDeTiempo):
    class Estado(models.TextChoices):
        CALCULANDO = "CALCULANDO", "Calculando"
        CALCULADA = "CALCULADA", "Calculada"
        FALLIDA = "FALLIDA", "Fallida"

    version = models.OneToOneField(VersionRuta, on_delete=models.PROTECT, related_name="calculo_vial")
    estado = models.CharField(max_length=16, choices=Estado.choices)
    intentos = models.PositiveIntegerField(default=1)
    token_intento = models.UUIDField()
    iniciada_en = models.DateTimeField()
    calculada_en = models.DateTimeField(null=True, blank=True)
    expira_en = models.DateTimeField(null=True, blank=True)
    reintento_desde = models.DateTimeField(null=True, blank=True)
    codigo_error = models.CharField(max_length=40, blank=True)
    origen_gps = models.JSONField(default=dict)
    paradas_calculadas = models.JSONField(default=list)
    # Solo coordenadas codificadas: no se persisten distancia, duración ni respuesta cruda de Google.
    polilinea_codificada = models.TextField(blank=True)
    polilineas_tramos = models.JSONField(default=list)

    class Meta:
        db_table = "calculos_ruta_vial"
        indexes = [models.Index(fields=("expira_en",), name="calculo_vial_expira_idx")]
        constraints = [models.CheckConstraint(condition=Q(intentos__gte=1), name="calculo_vial_intentos_ck")]


class ConsumoRutasGoogle(ModeloUUIDConMarcasDeTiempo):
    periodo = models.CharField(max_length=10, choices=(("DIARIO", "Diario"), ("MENSUAL", "Mensual")))
    fecha = models.DateField()
    intentos_reservados = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "consumo_rutas_google"
        constraints = [models.UniqueConstraint(fields=("periodo", "fecha"), name="consumo_google_periodo_uniq")]
