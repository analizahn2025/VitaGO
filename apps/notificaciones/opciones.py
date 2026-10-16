from django.db import models


class TipoNotificacion(models.TextChoices):
    REASIGNACION_PENDIENTE = "REASIGNACION_PENDIENTE", "Reasignación pendiente"
    SERVICIO_NO_ENTREGADO = "SERVICIO_NO_ENTREGADO", "Servicio no entregado"
    SOLICITUD_ASIGNADA = "SOLICITUD_ASIGNADA", "Solicitud asignada"
    SOLICITUD_REASIGNADA = "SOLICITUD_REASIGNADA", "Solicitud reasignada"
    SOLICITUD_RETIRADA = "SOLICITUD_RETIRADA", "Solicitud retirada"
    SOLICITUD_PRIORITARIA = "SOLICITUD_PRIORITARIA", "Solicitud prioritaria"
