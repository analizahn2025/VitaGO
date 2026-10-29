from django.contrib import admin

from apps.jornadas.models import AlmuerzoJornada, JornadaRepartidor


@admin.register(JornadaRepartidor)
class AdministracionJornadaRepartidor(admin.ModelAdmin):
    list_display = (
        "repartidor",
        "estado",
        "iniciada_en",
        "fecha_operativa", "cierre_programado_en",
        "finalizada_en",
        "servicios_completados",
        "kilometros_operativos",
    )
    list_filter = ("estado",)
    search_fields = ("repartidor__usuario__correo",)
    readonly_fields = (
        "fecha_operativa", "cierre_programado_en",
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

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AlmuerzoJornada)
class AdministracionAlmuerzoJornada(admin.ModelAdmin):
    list_display = ("jornada", "iniciada_en", "finalizada_en", "motivo_cierre")
    readonly_fields = ("jornada", "iniciada_en", "finalizada_en", "finalizada_por", "motivo_cierre", "creado_en", "actualizado_en")
    list_filter = ("finalizada_en",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

