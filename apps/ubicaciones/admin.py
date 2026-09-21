from django.contrib import admin

from apps.ubicaciones.models import TipoUbicacion, Ubicacion, UbicacionEmpresa


@admin.register(TipoUbicacion)
class AdministracionTipoUbicacion(admin.ModelAdmin):
    list_display = ("nombre", "codigo", "activo")
    list_filter = ("activo",)
    search_fields = ("nombre", "codigo")


@admin.register(Ubicacion)
class AdministracionUbicacion(admin.ModelAdmin):
    list_display = ("nombre", "tipo_ubicacion", "pais", "origen", "estado")
    list_filter = ("estado", "origen", "verificada", "pais")
    search_fields = ("nombre", "direccion", "identificador_lugar_google")


@admin.register(UbicacionEmpresa)
class AdministracionUbicacionEmpresa(admin.ModelAdmin):
    list_display = (
        "empresa",
        "ubicacion",
        "permite_origen",
        "permite_destino",
        "estado",
    )
    list_filter = ("estado", "permite_origen", "permite_destino")
    search_fields = ("empresa__nombre", "ubicacion__nombre")
