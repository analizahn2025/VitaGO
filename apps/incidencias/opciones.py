from django.db import models


class EstadoIncidencia(models.TextChoices):
    ABIERTA = "ABIERTA", "Abierta"
    EN_REVISION = "EN_REVISION", "En revisión"
    CERRADA = "CERRADA", "Cerrada"


class TipoEventoIncidencia(models.TextChoices):
    REPORTADA = "REPORTADA", "Reportada"
    EN_REVISION = "EN_REVISION", "En revisión"
    CERRADA = "CERRADA", "Cerrada"
    EVIDENCIA_REGISTRADA = "EVIDENCIA_REGISTRADA", "Evidencia registrada"

