from django.contrib import admin

from apps.usuarios.models import Permiso, PermisoRol, Rol, RolUsuario, Usuario


@admin.register(Usuario)
class AdministracionUsuario(admin.ModelAdmin):
    list_display = (
        "correo",
        "nombres",
        "apellidos",
        "empresa",
        "sucursal",
        "estado",
    )
    list_filter = ("estado", "es_personal", "es_superusuario", "empresa")
    search_fields = (
        "correo",
        "nombres",
        "apellidos",
        "identificador_autenticacion_externa",
    )
    readonly_fields = ("last_login", "creado_en", "actualizado_en")
    exclude = ("password",)


@admin.register(Rol)
class AdministracionRol(admin.ModelAdmin):
    list_display = (
        "codigo",
        "nombre",
        "permite_alcance_global",
        "permite_alcance_empresa",
        "permite_alcance_sucursal",
        "activo",
        "creado_en",
    )
    list_filter = (
        "activo",
        "permite_alcance_global",
        "permite_alcance_empresa",
        "permite_alcance_sucursal",
    )
    search_fields = ("codigo", "nombre")


@admin.register(Permiso)
class AdministracionPermiso(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "activo", "creado_en")
    list_filter = ("activo",)
    search_fields = ("codigo", "nombre")


@admin.register(PermisoRol)
class AdministracionPermisoRol(admin.ModelAdmin):
    list_display = ("rol", "permiso", "activo", "creado_en")
    list_filter = ("activo", "rol")
    search_fields = ("rol__codigo", "permiso__codigo")


@admin.register(RolUsuario)
class AdministracionRolUsuario(admin.ModelAdmin):
    list_display = (
        "usuario",
        "rol",
        "tipo_alcance",
        "empresa",
        "sucursal",
        "activo",
        "asignado_en",
    )
    list_filter = ("activo", "tipo_alcance", "rol")
    search_fields = ("usuario__correo", "rol__codigo")
    readonly_fields = ("asignado_en", "creado_en", "actualizado_en")
