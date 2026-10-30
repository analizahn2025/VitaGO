from django.urls import include, path

from apps.seguimiento.vistas import VistaSeguimientoSolicitud
from apps.solicitudes.vistas import (
    VistaCargaSolicitud,
    VistaAgrupacionesSolicitudes,
    VistaAsignacionSolicitud,
    VistaDetalleSolicitud,
    VistaListaCreacionSolicitudes,
    VistaListaTiposServicio,
    VistaOpcionesCreacionSolicitud,
    VistaResumenSolicitante,
    VistaTransicionSolicitud,
    VistaSincronizacionGPSMovimiento,
    VistaCantidadTubosSolicitud,
)

app_name = "solicitudes"

urlpatterns = [
    path("<uuid:solicitud_id>/carga/", VistaCargaSolicitud.as_view(), name="carga"),
    path("<uuid:solicitud_id>/cantidad-tubos/", VistaCantidadTubosSolicitud.as_view(), name="cantidad-tubos"),
    path("<uuid:solicitud_id>/sincronizacion-gps/", VistaSincronizacionGPSMovimiento.as_view(), name="sincronizacion-gps"),
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
        "agrupaciones/",
        VistaAgrupacionesSolicitudes.as_view(),
        name="agrupaciones",
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
