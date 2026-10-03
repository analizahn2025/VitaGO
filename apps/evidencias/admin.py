from django.contrib import admin

from apps.evidencias.models import EvidenciaSolicitud


@admin.register(EvidenciaSolicitud)
class AdministracionEvidenciaSolicitud(admin.ModelAdmin):
    list_display = (
        "solicitud",
        "tipo",
        "repartidor",
        "capturada_en",
        "creado_en",
    )
    list_filter = ("tipo",)
    search_fields = ("solicitud__numero", "repartidor__usuario__correo")
    readonly_fields = (
        "solicitud",
        "repartidor",
        "tipo",
        "clave_almacenamiento",
        "url_archivo",
        "tipo_contenido",
        "tamano_bytes",
        "latitud",
        "longitud",
        "capturada_en",
        "notas",
        "creado_en",
        "actualizado_en",
    )

