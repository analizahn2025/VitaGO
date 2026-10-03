from django.urls import include, path

from apps.seguimiento.vistas import VistaSeguimientoSolicitud
from apps.solicitudes.vistas import (
    VistaAsignacionSolicitud,
    VistaDetalleSolicitud,
    VistaListaCreacionSolicitudes,
    VistaListaTiposServicio,
    VistaOpcionesCreacionSolicitud,
    VistaResumenSolicitante,
    VistaTransicionSolicitud,
)

app_name = "solicitudes"

urlpatterns = [
    path(
        "",
        VistaListaCreacionSolicitudes.as_view(),
        name="lista-creacion",
    ),
    path(
        "tipos-servicio/",
        VistaListaTiposServicio.as_view(),
        name="tipos-servicio",
    ),
    path(
        "opciones-creacion/",
        VistaOpcionesCreacionSolicitud.as_view(),
        name="opciones-creacion",
    ),
    path(
        "resumen-solicitante/",
        VistaResumenSolicitante.as_view(),
        name="resumen-solicitante",
    ),
    path(
        "<uuid:solicitud_id>/asignaciones/",
        VistaAsignacionSolicitud.as_view(),
        name="asignacion",
    ),
    path(
        "<uuid:solicitud_id>/transiciones/",
        VistaTransicionSolicitud.as_view(),
        name="transicion",
    ),
    path(
        "<uuid:solicitud_id>/evidencias/",
        include("apps.evidencias.urls"),
    ),
    path(
        "<uuid:solicitud_id>/seguimiento/",
        VistaSeguimientoSolicitud.as_view(),
        name="seguimiento",
    ),
    path(
        "<uuid:solicitud_id>/",
        VistaDetalleSolicitud.as_view(),
        name="detalle",
    ),
]
