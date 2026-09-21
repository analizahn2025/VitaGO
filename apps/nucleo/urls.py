from django.urls import path

from apps.nucleo.views import verificar_salud

app_name = "nucleo"

urlpatterns = [
    path("salud/", verificar_salud, name="salud"),
]
