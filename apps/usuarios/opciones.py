from django.db import models


class EstadoUsuario(models.TextChoices):
    ACTIVO = "ACTIVO", "Activo"
    INACTIVO = "INACTIVO", "Inactivo"
    SUSPENDIDO = "SUSPENDIDO", "Suspendido"


class TipoAlcanceRol(models.TextChoices):
    GLOBAL = "GLOBAL", "Global"
    EMPRESA = "EMPRESA", "Empresa"
    SUCURSAL = "SUCURSAL", "Sucursal"
