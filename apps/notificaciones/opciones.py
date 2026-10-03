from django.db import models


class TipoNotificacion(models.TextChoices):
    SOLICITUD_ASIGNADA = "SOLICITUD_ASIGNADA", "Solicitud asignada"
    SOLICITUD_REASIGNADA = "SOLICITUD_REASIGNADA", "Solicitud reasignada"
    SOLICITUD_RETIRADA = "SOLICITUD_RETIRADA", "Solicitud retirada"
    SOLICITUD_PRIORITARIA = "SOLICITUD_PRIORITARIA", "Solicitud prioritaria"
