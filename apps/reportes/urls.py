from django.urls import path

from apps.reportes.vistas import VistaDescargaReporteMotoristas, VistaDescargaReporteServicios

app_name = "reportes"
urlpatterns = [
    path("motoristas/descargar/", VistaDescargaReporteMotoristas.as_view(), name="motoristas-descargar"),
    path("servicios/descargar/", VistaDescargaReporteServicios.as_view(), name="servicios-descargar"),
]
