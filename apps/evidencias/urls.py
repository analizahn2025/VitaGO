from django.urls import path

from apps.evidencias.vistas import (
    VistaArchivoEvidencia,
    VistaListaRegistroEvidencias,
)

app_name = "evidencias"

urlpatterns = [
    path(
        "",
        VistaListaRegistroEvidencias.as_view(),
        name="lista-registro",
    ),
    path(
        "<uuid:evidencia_id>/archivo/",
        VistaArchivoEvidencia.as_view(),
        name="archivo",
    ),
]

