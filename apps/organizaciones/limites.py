"""Administración auditada de cupos compartidos, sin bloquear filas de motoristas."""

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q, Subquery, Sum
from django.db.models.functions import Coalesce
from django.http import Http404
from django.urls import reverse
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.organizaciones.models import Empresa, HistorialLimitesMotoristas
from apps.organizaciones.opciones import EstadoOrganizacion
from apps.repartidores.limites import CAMPOS_LIMITES, limites_de_configuracion, obtener_configuracion_red
from apps.repartidores.models import Repartidor
from apps.solicitudes.models import Solicitud
from apps.solicitudes.opciones import ESTADOS_SOLICITUD_ACTIVOS
from apps.usuarios.servicios import obtener_alcances_permiso


def exigir_modo_red():
    if settings.MODO_APLICACION != "EXTERNO":
        raise NotFound("La configuración general de la red solo está disponible en Network.")


def _validar_carga_comprometida(motoristas, anteriores, nuevos):
    # Las asignaciones y correcciones adquieren este mismo bloqueo de configuración
    # después del motorista. No tomar aquí bloqueos de motoristas evita invertirlo.
    cargas = Solicitud.objects.filter(
        repartidor_asignado_id__in=Subquery(motoristas.values("pk")),
        estado__in=ESTADOS_SOLICITUD_ACTIVOS,
    ).values("repartidor_asignado_id").annotate(
        tubos=Coalesce(Sum("cantidad_tubos"), 0), solicitudes=Count("pk"),
        frascos=Coalesce(Sum("cantidad_frascos"), 0),
        frascos_desconocidos=Count("pk", filter=Q(cantidad_frascos__isnull=True)),
        desconocidas=Count("pk", filter=Q(cantidad_tubos__isnull=True)),
    )
    errores = {}
    if cargas.filter(tubos__gt=nuevos["limite_tubos"]).exists():
        errores["limite_tubos"] = "Hay motoristas con más tubos comprometidos que el límite propuesto."
    elif nuevos["limite_tubos"] < anteriores["limite_tubos"] and cargas.filter(desconocidas__gt=0).exists():
        errores["limite_tubos"] = "Complete las cantidades de tubos pendientes antes de reducir el límite."
    if cargas.filter(frascos__gt=nuevos["limite_frascos"]).exists():
        errores["limite_frascos"] = "Hay motoristas con más frascos comprometidos que el límite propuesto."
    elif nuevos["limite_frascos"] < anteriores["limite_frascos"] and cargas.filter(frascos_desconocidos__gt=0).exists():
        errores["limite_frascos"] = "Complete las cantidades de frascos pendientes antes de reducir el límite."
    if cargas.filter(solicitudes__gt=nuevos["limite_solicitudes"]).exists():
        errores["limite_solicitudes"] = "Hay motoristas con más solicitudes activas que el límite propuesto."
    if errores:
        raise ValidationError(errores)


def _aplicar_limites(usuario, configuracion, datos, motoristas, *, empresa=None):
    anteriores = limites_de_configuracion(configuracion)
    nuevos = dict(anteriores)
    for clave in CAMPOS_LIMITES:
        if clave in datos:
            valor = datos[clave]
            maximo = 5 if clave == "limite_solicitudes" else 2147483647
            if isinstance(valor, bool) or not isinstance(valor, int) or not 1 <= valor <= maximo:
                raise ValidationError({clave: f"Debe indicar un entero entre 1 y {maximo}."})
            nuevos[clave] = valor
    if anteriores == nuevos:
        return configuracion
    _validar_carga_comprometida(motoristas, anteriores, nuevos)
    for clave, campo in CAMPOS_LIMITES.items():
        setattr(configuracion, campo, nuevos[clave])
    configuracion.save(update_fields=(*CAMPOS_LIMITES.values(), "actualizado_en"))
    HistorialLimitesMotoristas.objects.create(
        empresa=empresa, realizado_por=usuario,
        limites_anteriores=anteriores, limites_nuevos=nuevos,
        motivo=datos.get("motivo") or "Configuración general de los cupos de motoristas.",
    )
    if empresa and any(nuevos[clave] > anteriores[clave] for clave in nuevos):
        from apps.solicitudes.servicios import programar_reintento_pendientes
        programar_reintento_pendientes(empresa.pk)
    return configuracion


@transaction.atomic
def configurar_limites_empresa(usuario, identificador, datos):
    if settings.MODO_APLICACION != "CORPORATIVO":
        ruta = reverse("organizaciones:limites-motoristas-red")
        raise ValidationError({"detail": f"Network usa límites generales. Use {ruta}."})
    alcances = obtener_alcances_permiso(usuario, "empresa.administrar")
    if not alcances.tiene_algun_alcance:
        raise PermissionDenied('No tiene el permiso requerido: "empresa.administrar".')
    if not alcances.permite_todas_las_sucursales_de(identificador):
        raise Http404("La empresa no existe o no está dentro de su alcance.")
    try:
        empresa = Empresa.objects.select_for_update(no_key=True).get(pk=identificador, estado=EstadoOrganizacion.ACTIVO)
    except Empresa.DoesNotExist as error:
        raise Http404("La empresa no existe o está inactiva.") from error
    return _aplicar_limites(
        usuario, empresa, datos, Repartidor.objects.filter(empresa=empresa), empresa=empresa,
    )


@transaction.atomic
def configurar_limites_red(usuario, datos):
    exigir_modo_red()
    if not obtener_alcances_permiso(usuario, "configuracion.administrar").global_:
        raise PermissionDenied('Requiere "configuracion.administrar" con alcance global.')
    return _aplicar_limites(
        usuario, obtener_configuracion_red(bloquear=True), datos,
        Repartidor.objects.filter(empresa__isnull=True),
    )
