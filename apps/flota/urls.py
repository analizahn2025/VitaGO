from django.urls import path

from apps.flota.vistas import VistaDetalleVehiculo, VistaListaCreacionVehiculos

app_name = "flota"

urlpatterns = [
    path("", VistaListaCreacionVehiculos.as_view(), name="lista-creacion"),
    path("<uuid:vehiculo_id>/", VistaDetalleVehiculo.as_view(), name="detalle"),
]
