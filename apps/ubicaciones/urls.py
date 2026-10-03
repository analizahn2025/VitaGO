from django.urls import path

from apps.ubicaciones.vistas import (
    VistaAutorizacionUbicacionEmpresa,
    VistaDetalleUbicacion,
    VistaListaCreacionUbicaciones,
    VistaListaTiposUbicacion,
)

app_name = "ubicaciones"

urlpatterns = [
    path(
        "",
        VistaListaCreacionUbicaciones.as_view(),
        name="lista-creacion-ubicaciones",
    ),
    path(
        "tipos/",
        VistaListaTiposUbicacion.as_view(),
        name="lista-tipos",
    ),
    path(
        "<uuid:ubicacion_id>/",
        VistaDetalleUbicacion.as_view(),
        name="detalle-ubicacion",
    ),
    path(
        "<uuid:ubicacion_id>/autorizacion-empresa/<uuid:empresa_id>/",
        VistaAutorizacionUbicacionEmpresa.as_view(),
        name="autorizacion-empresa",
    ),
]
