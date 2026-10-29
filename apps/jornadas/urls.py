from django.urls import path

from apps.jornadas.vistas import (
    VistaDetalleJornada,
    VistaFinalizacionJornada,
    VistaInicioJornada,
    VistaJornadaActiva,
    VistaListaJornadas,
    VistaSincronizacionGPSJornada,
    VistaRevisionesKilometraje,
    VistaInicioAlmuerzo, VistaFinAlmuerzo,
)

app_name = "jornadas"

urlpatterns = [
    path("<uuid:jornada_id>/almuerzo/iniciar/", VistaInicioAlmuerzo.as_view(), name="iniciar-almuerzo"),
    path("<uuid:jornada_id>/almuerzo/finalizar/", VistaFinAlmuerzo.as_view(), name="finalizar-almuerzo"),
    path("<uuid:jornada_id>/kilometraje/revisiones/", VistaRevisionesKilometraje.as_view(), name="revisiones-kilometraje"),
    path("<uuid:jornada_id>/sincronizacion-gps/", VistaSincronizacionGPSJornada.as_view(), name="sincronizacion-gps"),
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

