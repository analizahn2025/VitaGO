from django.db import models


class MotivoRevocacionSesion(models.TextChoices):
    ROTACION = "ROTACION", "Rotación del token de refresco"
    CIERRE_SESION = "CIERRE_SESION", "Cierre de sesión"
    CIERRE_TOTAL = "CIERRE_TOTAL", "Cierre de todas las sesiones"
    REUTILIZACION_TOKEN = "REUTILIZACION_TOKEN", "Reutilización de token"
    USUARIO_INACTIVO = "USUARIO_INACTIVO", "Usuario inactivo"
    EXPIRACION = "EXPIRACION", "Expiración"
