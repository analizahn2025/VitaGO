from django.conf import settings
from rest_framework import serializers

from apps.notificaciones.models import NotificacionUsuario


class SerializadorNotificacion(serializers.ModelSerializer):
    ruta = serializers.SerializerMethodField()
    enlace_profundo = serializers.SerializerMethodField()
    leida = serializers.SerializerMethodField()

    def get_ruta(self, notificacion):
        return f"/solicitudes/{notificacion.solicitud_id}"

    def get_enlace_profundo(self, notificacion):
        esquema = (
            "vitago-corporate"
            if settings.MODO_APLICACION == "CORPORATIVO"
            else "vitago-network"
        )
        return f"{esquema}://{self.get_ruta(notificacion)}"

    def get_leida(self, notificacion):
        return notificacion.leida_en is not None

    class Meta:
        model = NotificacionUsuario
        fields = (
            "id",
            "tipo",
            "titulo",
            "mensaje",
            "solicitud_id",
            "ruta",
            "enlace_profundo",
            "leida",
            "leida_en",
            "creado_en",
        )
