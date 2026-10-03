from django.contrib import admin

from apps.flota.models import Vehiculo


@admin.register(Vehiculo)
class AdministracionVehiculo(admin.ModelAdmin):
    list_display = ("placa", "tipo", "empresa", "estado")
    list_filter = ("tipo", "estado")
    search_fields = ("placa", "marca", "modelo")
