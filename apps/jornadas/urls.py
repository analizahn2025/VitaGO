from django.urls import path

from apps.jornadas.vistas import (
    VistaDetalleJornada,
    VistaFinalizacionJornada,
    VistaInicioJornada,
    VistaJornadaActiva,
    VistaListaJornadas,
)

app_name = "jornadas"

urlpatterns = [
    path("", VistaListaJornadas.as_view(), name="lista"),
    path("iniciar/", VistaInicioJornada.as_view(), name="iniciar"),
    path("activa/", VistaJornadaActiva.as_view(), name="activa"),
    path("<uuid:jornada_id>/", VistaDetalleJornada.as_view(), name="detalle"),
    path(
        "<uuid:jornada_id>/finalizar/",
        VistaFinalizacionJornada.as_view(),
        name="finalizar",
    ),
]

