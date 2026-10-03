from django.urls import path

from apps.incidencias.vistas import (
    VistaArchivoEvidenciaIncidencia,
    VistaDetalleIncidencia,
    VistaListaCreacionIncidencias,
    VistaListaRegistroEvidenciasIncidencia,
    VistaRevisionIncidencia,
)

app_name = "incidencias"

urlpatterns = [
    path("", VistaListaCreacionIncidencias.as_view(), name="lista-creacion"),
    path(
        "<uuid:incidencia_id>/",
        VistaDetalleIncidencia.as_view(),
        name="detalle",
    ),
    path(
        "<uuid:incidencia_id>/revision/",
        VistaRevisionIncidencia.as_view(),
        name="revision",
    ),
    path(
        "<uuid:incidencia_id>/evidencias/",
        VistaListaRegistroEvidenciasIncidencia.as_view(),
        name="evidencias",
    ),
    path(
        "<uuid:incidencia_id>/evidencias/<uuid:evidencia_id>/archivo/",
        VistaArchivoEvidenciaIncidencia.as_view(),
        name="archivo-evidencia",
    ),
]
