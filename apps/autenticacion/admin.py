from django.contrib import admin

from apps.autenticacion.models import SesionAutenticacion


@admin.register(SesionAutenticacion)
class AdministracionSesionAutenticacion(admin.ModelAdmin):
    list_display = (
        "usuario",
        "identificador_dispositivo",
        "direccion_ip",
        "creado_en",
        "expira_en",
        "revocado_en",
        "motivo_revocacion",
    )
    list_filter = ("motivo_revocacion", "creado_en", "expira_en")
    search_fields = (
        "usuario__correo",
        "identificador_token",
        "identificador_dispositivo",
    )
    exclude = ("hash_token_refresco",)
    readonly_fields = (
        "usuario",
        "identificador_token",
        "familia",
        "identificador_dispositivo",
        "direccion_ip",
        "agente_usuario",
        "expira_en",
        "ultimo_uso_en",
        "revocado_en",
        "motivo_revocacion",
        "reemplazada_por",
        "creado_en",
        "actualizado_en",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
