from django.db import models


class TipoVehiculo(models.TextChoices):
    MOTOCICLETA = "MOTOCICLETA", "Motocicleta"
    AUTOMOVIL = "AUTOMOVIL", "Automóvil"
    PANEL = "PANEL", "Panel"
    ESPECIAL = "ESPECIAL", "Especial"
    OTRO = "OTRO", "Otro"


class EstadoVehiculo(models.TextChoices):
    ACTIVO = "ACTIVO", "Activo"
    MANTENIMIENTO = "MANTENIMIENTO", "En mantenimiento"
    FUERA_SERVICIO = "FUERA_SERVICIO", "Fuera de servicio"
    INACTIVO = "INACTIVO", "Inactivo"
