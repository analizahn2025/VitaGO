from django.contrib import admin

from apps.seguimiento.models import RegistroUbicacion, RevisionKilometraje


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
        "sesion_gps", "secuencia",
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


@admin.register(RevisionKilometraje)
class AdministracionRevisionKilometraje(admin.ModelAdmin):
    list_display = ("jornada", "movimiento_especial", "numero", "motivo", "kilometros", "creado_en")
    readonly_fields = tuple(campo.name for campo in RevisionKilometraje._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

