from django.urls import path

from apps.usuarios.vistas import (
    VistaDetalleActualizacionUsuario,
    VistaListaCreacionUsuarios,
    VistaMiPerfil,
    VistaRestablecimientoContrasena,
    VistaRevocacionRolUsuario,
    VistaRolesAsignables,
    VistaRolesUsuario,
)

app_name = "usuarios"

urlpatterns = [
    path("", VistaListaCreacionUsuarios.as_view(), name="lista-creacion"),
    path("mi-perfil/", VistaMiPerfil.as_view(), name="mi-perfil"),
    path(
        "roles-asignables/",
        VistaRolesAsignables.as_view(),
        name="roles-asignables",
    ),
    path(
        "<uuid:usuario_id>/",
        VistaDetalleActualizacionUsuario.as_view(),
        name="detalle-actualizacion",
    ),
    path(
        "<uuid:usuario_id>/restablecer-contrasena/",
        VistaRestablecimientoContrasena.as_view(),
        name="restablecer-contrasena",
    ),
    path(
        "<uuid:usuario_id>/roles/",
        VistaRolesUsuario.as_view(),
        name="roles-usuario",
    ),
    path(
        "<uuid:usuario_id>/roles/<uuid:asignacion_id>/",
        VistaRevocacionRolUsuario.as_view(),
        name="revocar-rol-usuario",
    ),
]
