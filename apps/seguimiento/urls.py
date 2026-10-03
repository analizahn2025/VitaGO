from django.urls import path

from apps.seguimiento.vistas import VistaRegistroUbicaciones

app_name = "seguimiento"

urlpatterns = [
    path("registros/", VistaRegistroUbicaciones.as_view(), name="registros"),
]
