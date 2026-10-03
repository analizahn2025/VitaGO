from django.db import models


class TipoEvidenciaSolicitud(models.TextChoices):
    FOTO_RECOLECCION = "FOTO_RECOLECCION", "Fotografía de recolección"
    FOTO_ENTREGA = "FOTO_ENTREGA", "Fotografía de entrega"
    FOTO_INCIDENCIA = "FOTO_INCIDENCIA", "Fotografía de incidencia"

