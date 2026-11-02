from django.urls import path

from apps.seguimiento.vistas import VistaConfiguracionGPS, VistaRegistroUbicaciones, VistaMotoristasEnJornada

app_name = "seguimiento"

urlpatterns = [
    path("motoristas/", VistaMotoristasEnJornada.as_view(), name="motoristas"),
    path("configuracion/", VistaConfiguracionGPS.as_view(), name="configuracion"),
    path("registros/", VistaRegistroUbicaciones.as_view(), name="registros"),
]
