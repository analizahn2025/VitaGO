from django.contrib import admin

from apps.organizaciones.models import Empresa, HistorialLimitesMotoristas, Sucursal


@admin.register(Empresa)
class AdministracionEmpresa(admin.ModelAdmin):
    list_display = ("nombre", "pais", "estado", "creado_en")
    list_filter = ("estado", "pais")
    search_fields = ("nombre", "razon_social", "identificacion_fiscal")
    # Las modificaciones de límites pasan por el servicio transaccional y su auditoría.
    readonly_fields = ("limite_tubos_por_motorista", "limite_solicitudes_por_motorista")


@admin.register(HistorialLimitesMotoristas)
class AdministracionHistorialLimitesMotoristas(admin.ModelAdmin):
    list_display = ("empresa", "realizado_por", "creado_en")
    readonly_fields = (
        "empresa", "realizado_por", "limites_anteriores", "limites_nuevos",
        "motivo", "creado_en", "actualizado_en",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Sucursal)
class AdministracionSucursal(admin.ModelAdmin):
    list_display = ("nombre", "empresa", "estado", "creado_en")
    list_filter = ("estado", "empresa")
    search_fields = ("nombre", "codigo", "empresa__nombre")
