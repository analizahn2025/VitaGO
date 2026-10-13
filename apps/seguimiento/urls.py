from django.urls import path

from apps.seguimiento.vistas import VistaConfiguracionGPS, VistaRegistroUbicaciones

app_name = "seguimiento"

urlpatterns = [
    path("configuracion/", VistaConfiguracionGPS.as_view(), name="configuracion"),
    path("registros/", VistaRegistroUbicaciones.as_view(), name="registros"),
]
