"""Root URL configuration for VitaGo."""

from django.urls import include, path

urlpatterns = [
    path("api/v1/", include("apps.nucleo.urls")),
    path("api/v1/autenticacion/", include("apps.autenticacion.urls")),
    path("api/v1/usuarios/", include("apps.usuarios.urls")),
    path("api/v1/organizaciones/", include("apps.organizaciones.urls")),
    path("api/v1/ubicaciones/", include("apps.ubicaciones.urls")),
    path("api/v1/vehiculos/", include("apps.flota.urls")),
    path("api/v1/repartidores/", include("apps.repartidores.urls")),
    path("api/v1/solicitudes/", include("apps.solicitudes.urls")),
    path("api/v1/notificaciones/", include("apps.notificaciones.urls")),
    path("api/v1/jornadas/", include("apps.jornadas.urls")),
    path("api/v1/seguimiento/", include("apps.seguimiento.urls")),
    path("api/v1/incidencias/", include("apps.incidencias.urls")),
]
