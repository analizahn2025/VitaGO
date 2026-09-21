from django.urls import path

from apps.autenticacion.vistas import (
    VistaCierreSesion,
    VistaCierreTotalSesiones,
    VistaInicioSesion,
    VistaRenovacionToken,
)

app_name = "autenticacion"

urlpatterns = [
    path(
        "iniciar-sesion/",
        VistaInicioSesion.as_view(),
        name="iniciar-sesion",
    ),
    path("renovar/", VistaRenovacionToken.as_view(), name="renovar"),
    path(
        "cerrar-sesion/",
        VistaCierreSesion.as_view(),
        name="cerrar-sesion",
    ),
    path(
        "cerrar-todas-las-sesiones/",
        VistaCierreTotalSesiones.as_view(),
        name="cerrar-todas-las-sesiones",
    ),
]
