from django.db import models


class EstadoOperativoRepartidor(models.TextChoices):
    DESCONECTADO = "OFFLINE", "Desconectado"
    DISPONIBLE = "AVAILABLE", "Disponible"
    EN_RUTA = "ON_ROUTE", "En ruta"
    PAUSADO = "PAUSED", "Pausado"
    FUERA_SERVICIO = "OUT_OF_SERVICE", "Fuera de servicio"


class CapacidadRepartidor(models.TextChoices):
    VACIO = "EMPTY", "Vacío"
    ESPACIO_DISPONIBLE = "AVAILABLE_SPACE", "Con espacio disponible"
    LLENO = "FULL", "Lleno"
