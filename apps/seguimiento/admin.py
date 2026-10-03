from django.contrib import admin

from apps.seguimiento.models import RegistroUbicacion


@admin.register(RegistroUbicacion)
class AdministracionRegistroUbicacion(admin.ModelAdmin):
    list_display = (
        "repartidor",
        "jornada",
        "registrada_en",
        "es_operativo",
        "precision_metros",
    )
    list_filter = ("es_operativo",)
    search_fields = ("repartidor__usuario__correo", "id_cliente")
    readonly_fields = (
        "id_cliente",
        "repartidor",
        "jornada",
        "latitud",
        "longitud",
        "precision_metros",
        "velocidad_metros_segundo",
        "rumbo_grados",
        "registrada_en",
        "es_operativo",
        "creado_en",
        "actualizado_en",
    )

