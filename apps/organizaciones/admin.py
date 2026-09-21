from django.contrib import admin

from apps.organizaciones.models import Empresa, Sucursal


@admin.register(Empresa)
class AdministracionEmpresa(admin.ModelAdmin):
    list_display = ("nombre", "pais", "estado", "creado_en")
    list_filter = ("estado", "pais")
    search_fields = ("nombre", "razon_social", "identificacion_fiscal")


@admin.register(Sucursal)
class AdministracionSucursal(admin.ModelAdmin):
    list_display = ("nombre", "empresa", "estado", "creado_en")
    list_filter = ("estado", "empresa")
    search_fields = ("nombre", "codigo", "empresa__nombre")
