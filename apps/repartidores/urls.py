from django.urls import path

from apps.repartidores.vistas import (
    VistaDetalleRepartidor,
    VistaListaCreacionRepartidores,
    VistaMiPerfilRepartidor,
    VistaOperacionRepartidor,
    VistaRepartidoresDisponibles,
)

app_name = "repartidores"

urlpatterns = [
    path("", VistaListaCreacionRepartidores.as_view(), name="lista-creacion"),
    path("disponibles/", VistaRepartidoresDisponibles.as_view(), name="disponibles"),
    path("mi-perfil/", VistaMiPerfilRepartidor.as_view(), name="mi-perfil"),
    path("<uuid:repartidor_id>/", VistaDetalleRepartidor.as_view(), name="detalle"),
    path(
        "<uuid:repartidor_id>/operacion/",
        VistaOperacionRepartidor.as_view(),
        name="operacion",
    ),
]
