from django.db import models


class PrioridadSolicitud(models.TextChoices):
    NORMAL = "NORMAL", "Normal"
    PRIORITARIA = "PRIORITY", "Prioritaria"


class ModalidadSolicitud(models.TextChoices):
    ABIERTO = "ABIERTO", "Abierto"
    ENTRE_SUCURSALES = "ENTRE_SUCURSALES", "Entre sucursales"
    EMPRESA_TRANSPORTE = "EMPRESA_TRANSPORTE", "Empresa de transporte"
    ESPECIAL = "ESPECIAL", "Envío especial"


class EstadoMovimientoEnvioEspecial(models.TextChoices):
    ACTIVO = "ACTIVO", "Activo"
    FINALIZADO = "FINALIZADO", "Finalizado"


class EstadoSolicitud(models.TextChoices):
    PENDIENTE = "PENDING", "Pendiente"
    ASIGNADA = "ASSIGNED", "Asignada"
    HACIA_RECOLECCION = "GOING_TO_PICKUP", "Hacia recolección"
    EN_RECOLECCION = "AT_PICKUP", "En recolección"
    RECOLECTADA = "PICKED_UP", "Recolectada"
    EN_TRANSITO = "IN_TRANSIT", "En tránsito"
    EN_DESTINO = "AT_DESTINATION", "En destino"
    ENTREGADA = "DELIVERED", "Entregada"
    CANCELADA = "CANCELLED", "Cancelada"
    RECOLECCION_FALLIDA = "PICKUP_FAILED", "Recolección fallida"
    ENTREGA_FALLIDA = "DELIVERY_FAILED", "Entrega fallida"


ESTADOS_SOLICITUD_ACTIVOS = (
    EstadoSolicitud.ASIGNADA,
    EstadoSolicitud.HACIA_RECOLECCION,
    EstadoSolicitud.EN_RECOLECCION,
    EstadoSolicitud.RECOLECTADA,
    EstadoSolicitud.EN_TRANSITO,
    EstadoSolicitud.EN_DESTINO,
)


class TipoEventoSolicitud(models.TextChoices):
    CREADA = "CREADA", "Creada"
    ASIGNADA = "ASIGNADA", "Asignada"
    REASIGNADA = "REASIGNADA", "Reasignada"
    HACIA_RECOLECCION = "HACIA_RECOLECCION", "Hacia recolección"
    LLEGADA_RECOLECCION = "LLEGADA_RECOLECCION", "Llegada a recolección"
    RECOLECTADA = "RECOLECTADA", "Recolectada"
    EN_TRANSITO = "EN_TRANSITO", "En tránsito"
    LLEGADA_DESTINO = "LLEGADA_DESTINO", "Llegada a destino"
    ENTREGADA = "ENTREGADA", "Entregada"
    CANCELADA = "CANCELADA", "Cancelada"
    RECOLECCION_FALLIDA = "RECOLECCION_FALLIDA", "Recolección fallida"
    ENTREGA_FALLIDA = "ENTREGA_FALLIDA", "Entrega fallida"
    EVIDENCIA_REGISTRADA = "EVIDENCIA_REGISTRADA", "Evidencia registrada"


class TipoAsignacionSolicitud(models.TextChoices):
    MANUAL = "MANUAL", "Manual"
    AUTOMATICA = "AUTOMATICA", "Automática"


class EstadoAsignacionSolicitud(models.TextChoices):
    ACTIVA = "ACTIVA", "Activa"
    FINALIZADA = "FINALIZADA", "Finalizada"
    CANCELADA = "CANCELADA", "Cancelada"
    REASIGNADA = "REASIGNADA", "Reasignada"
