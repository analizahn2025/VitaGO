"""Root URL configuration for VitaGo."""

from django.urls import include, path

urlpatterns = [
    path("api/v1/", include("apps.nucleo.urls")),
    path("api/v1/autenticacion/", include("apps.autenticacion.urls")),
]
