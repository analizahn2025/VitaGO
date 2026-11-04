from django.urls import path

from apps.reportes.vistas import VistaDescargaReporteMotoristas

app_name = "reportes"
urlpatterns = [
    path("motoristas/descargar/", VistaDescargaReporteMotoristas.as_view(), name="motoristas-descargar"),
]
