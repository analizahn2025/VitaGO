from django.urls import path

from apps.rutas.vistas import (
    VistaDetalleVersionRuta,
    VistaMiRuta,
    VistaCalcularMiRuta,
    VistaRutasHistoricas,
    VistaVersionesRuta,
)


app_name = "rutas"

urlpatterns = [
    path("mi-ruta/", VistaMiRuta.as_view(), name="mi-ruta"),
    path("mi-ruta/calcular/", VistaCalcularMiRuta.as_view(), name="calcular-mi-ruta"),
    path("", VistaRutasHistoricas.as_view(), name="listar-rutas"),
    path(
        "<uuid:ruta_id>/versiones/",
        VistaVersionesRuta.as_view(),
        name="listar-versiones",
    ),
    path(
        "<uuid:ruta_id>/versiones/<int:numero>/",
        VistaDetalleVersionRuta.as_view(),
        name="detalle-version",
    ),
]
