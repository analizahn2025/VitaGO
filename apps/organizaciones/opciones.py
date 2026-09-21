from django.db import models


class EstadoOrganizacion(models.TextChoices):
    ACTIVO = "ACTIVO", "Activo"
    INACTIVO = "INACTIVO", "Inactivo"
    SUSPENDIDO = "SUSPENDIDO", "Suspendido"
