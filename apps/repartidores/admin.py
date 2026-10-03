from django.contrib import admin

from apps.repartidores.models import HistorialEstadoRepartidor, Repartidor


@admin.register(Repartidor)
class AdministracionRepartidor(admin.ModelAdmin):
    list_display = (
        "usuario",
        "empresa",
        "vehiculo",
        "estado_operativo",
        "capacidad",
        "activo",
    )
    list_filter = ("estado_operativo", "capacidad", "activo")
    search_fields = ("usuario__correo", "usuario__nombres", "usuario__apellidos")


@admin.register(HistorialEstadoRepartidor)
class AdministracionHistorialEstadoRepartidor(admin.ModelAdmin):
    list_display = (
        "repartidor",
        "estado_anterior",
        "estado_nuevo",
        "realizado_por",
        "creado_en",
    )
    readonly_fields = (
        "repartidor",
        "estado_anterior",
        "estado_nuevo",
        "capacidad_anterior",
        "capacidad_nueva",
        "realizado_por",
        "motivo",
        "creado_en",
        "actualizado_en",
    )
