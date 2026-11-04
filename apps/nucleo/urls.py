from django.urls import path

from apps.nucleo.views import verificar_salud, verificar_disponibilidad

app_name = "nucleo"

urlpatterns = [
    path("salud/disponibilidad/", verificar_disponibilidad, name="disponibilidad"),
    path("salud/", verificar_salud, name="salud"),
]
