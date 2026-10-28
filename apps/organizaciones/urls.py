from django.urls import path

from apps.organizaciones.vistas import (
    VistaDetalleEmpresa,
    VistaDetalleSucursal,
    VistaListaEmpresas,
    VistaListaSucursalesEmpresa,
    VistaLimitesMotoristasEmpresa,
    VistaLimitesMotoristasRed,
)

app_name = "organizaciones"

urlpatterns = [
    path("configuracion/limites-motoristas/", VistaLimitesMotoristasRed.as_view(), name="limites-motoristas-red"),
    path("empresas/<uuid:empresa_id>/limites-motoristas/", VistaLimitesMotoristasEmpresa.as_view(), name="limites-motoristas-empresa"),
    path("empresas/", VistaListaEmpresas.as_view(), name="lista-empresas"),
    path(
        "empresas/<uuid:empresa_id>/",
        VistaDetalleEmpresa.as_view(),
        name="detalle-empresa",
    ),
    path(
        "empresas/<uuid:empresa_id>/sucursales/",
        VistaListaSucursalesEmpresa.as_view(),
        name="lista-sucursales-empresa",
    ),
    path(
        "sucursales/<uuid:sucursal_id>/",
        VistaDetalleSucursal.as_view(),
        name="detalle-sucursal",
    ),
]
