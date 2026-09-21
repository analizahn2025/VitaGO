from django.contrib import admin

from apps.geografia.models import Pais


@admin.register(Pais)
class AdministracionPais(admin.ModelAdmin):
    list_display = ("nombre", "iso2", "codigo_moneda", "activo")
    list_filter = ("activo",)
    search_fields = ("nombre", "iso2", "iso3")
