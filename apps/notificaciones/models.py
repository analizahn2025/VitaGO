from django.db import models

from apps.nucleo.models import ModeloUUIDConMarcasDeTiempo
from apps.notificaciones.opciones import TipoNotificacion


class NotificacionUsuario(ModeloUUIDConMarcasDeTiempo):
    usuario = models.ForeignKey(
        "usuarios.Usuario",
        on_delete=models.PROTECT,
        related_name="notificaciones",
    )
    solicitud = models.ForeignKey(
        "solicitudes.Solicitud",
        on_delete=models.PROTECT,
        related_name="notificaciones",
    )
    evento = models.ForeignKey(
        "solicitudes.EventoSolicitud",
        on_delete=models.PROTECT,
        related_name="notificaciones",
    )
    tipo = models.CharField(max_length=40, choices=TipoNotificacion.choices)
    titulo = models.CharField(max_length=160)
    mensaje = models.TextField()
    leida_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notificaciones_usuario"
        ordering = ("-creado_en", "-id")
        indexes = [
            models.Index(
                fields=("usuario", "leida_en", "-creado_en"),
                name="notif_usuario_lectura_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("usuario", "evento"),
                name="notif_usuario_evento_uniq",
            ),
        ]

    def __str__(self):
        return f"{self.usuario.correo} - {self.titulo}"
