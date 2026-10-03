from django.contrib import admin

from apps.jornadas.models import JornadaRepartidor


@admin.register(JornadaRepartidor)
class AdministracionJornadaRepartidor(admin.ModelAdmin):
    list_display = (
        "repartidor",
        "estado",
        "iniciada_en",
        "finalizada_en",
        "servicios_completados",
        "kilometros_operativos",
    )
    list_filter = ("estado",)
    search_fields = ("repartidor__usuario__correo",)
    readonly_fields = (
        "repartidor",
        "estado",
        "iniciada_en",
        "finalizada_en",
        "latitud_inicio",
        "longitud_inicio",
        "latitud_fin",
        "longitud_fin",
        "kilometros_operativos",
        "servicios_completados",
        "recolecciones_completadas",
        "entregas_completadas",
        "servicios_normales",
        "servicios_prioritarios",
        "minutos_activos",
        "incidencias_reportadas",
        "creado_en",
        "actualizado_en",
    )

