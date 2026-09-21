from django.db import models


class OrigenUbicacion(models.TextChoices):
    GOOGLE = "GOOGLE", "Google"
    REGISTRADA_USUARIO = "REGISTRADA_USUARIO", "Registrada por usuario"


class EstadoUbicacion(models.TextChoices):
    ACTIVO = "ACTIVO", "Activo"
    INACTIVO = "INACTIVO", "Inactivo"


class EstadoUbicacionEmpresa(models.TextChoices):
    PENDIENTE = "PENDIENTE", "Pendiente"
    APROBADO = "APROBADO", "Aprobado"
    RECHAZADO = "RECHAZADO", "Rechazado"
    INACTIVO = "INACTIVO", "Inactivo"
