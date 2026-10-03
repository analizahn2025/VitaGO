from django.urls import path

from apps.notificaciones.vistas import (
    VistaConteoNoLeidas,
    VistaListaNotificaciones,
    VistaMarcarNotificacionLeida,
)

app_name = "notificaciones"

urlpatterns = [
    path("", VistaListaNotificaciones.as_view(), name="lista"),
    path("conteo-no-leidas/", VistaConteoNoLeidas.as_view(), name="conteo-no-leidas"),
    path(
        "<uuid:notificacion_id>/marcar-leida/",
        VistaMarcarNotificacionLeida.as_view(),
        name="marcar-leida",
    ),
]
