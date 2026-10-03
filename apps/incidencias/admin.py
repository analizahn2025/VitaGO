from django.contrib import admin

from apps.incidencias.models import (
    EventoIncidencia,
    EvidenciaIncidencia,
    Incidencia,
)


@admin.register(Incidencia)
class AdministracionIncidencia(admin.ModelAdmin):
    list_display = (
        "repartidor",
        "jornada",
        "solicitud",
        "estado",
        "reportada_en",
    )
    list_filter = ("estado",)
    search_fields = ("repartidor__usuario__correo", "descripcion")
    readonly_fields = tuple(
        campo.name for campo in Incidencia._meta.fields
    )


@admin.register(EventoIncidencia)
class AdministracionEventoIncidencia(admin.ModelAdmin):
    list_display = ("incidencia", "tipo", "realizado_por", "creado_en")
    list_filter = ("tipo",)
    readonly_fields = tuple(
        campo.name for campo in EventoIncidencia._meta.fields
    )


@admin.register(EvidenciaIncidencia)
class AdministracionEvidenciaIncidencia(admin.ModelAdmin):
    list_display = ("incidencia", "repartidor", "capturada_en")
    readonly_fields = tuple(
        campo.name for campo in EvidenciaIncidencia._meta.fields
    )

