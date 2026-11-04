from django.urls import path

from apps.repartidores.vistas import (
    VistaDetalleRepartidor,
    VistaListaCreacionRepartidores,
    VistaMiPerfilRepartidor,
    VistaOperacionRepartidor,
    VistaRepartidoresDisponibles,
    VistaResumenesMotoristas,
    VistaResumenMotorista,
    VistaTemperaturasMotorista,
    VistaDepartamentosRepartidores,
    VistaCoberturaRepartidor,
)

app_name = "repartidores"

urlpatterns = [
    path("", VistaListaCreacionRepartidores.as_view(), name="lista-creacion"),
    path("disponibles/", VistaRepartidoresDisponibles.as_view(), name="disponibles"),
    path("departamentos/", VistaDepartamentosRepartidores.as_view(), name="departamentos"),
    path("<uuid:repartidor_id>/cobertura/", VistaCoberturaRepartidor.as_view(), name="cobertura"),
    path("resumenes/", VistaResumenesMotoristas.as_view(), name="resumenes"),
    path("<uuid:repartidor_id>/resumen/", VistaResumenMotorista.as_view(), name="resumen"),
    path("<uuid:repartidor_id>/temperaturas/", VistaTemperaturasMotorista.as_view(), name="temperaturas"),
    path("mi-perfil/", VistaMiPerfilRepartidor.as_view(), name="mi-perfil"),
    path("<uuid:repartidor_id>/", VistaDetalleRepartidor.as_view(), name="detalle"),
    path(
        "<uuid:repartidor_id>/operacion/",
        VistaOperacionRepartidor.as_view(),
        name="operacion",
    ),
]
