"""Operaciones transaccionales de empresas y sucursales."""

from django.db import transaction
from django.http import Http404
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.organizaciones.models import Empresa, Sucursal
from apps.organizaciones.opciones import EstadoOrganizacion
from apps.ubicaciones.models import UbicacionEmpresa
from apps.ubicaciones.opciones import EstadoUbicacion, EstadoUbicacionEmpresa
from apps.usuarios.servicios import obtener_alcances_permiso


@transaction.atomic
def crear_sucursal(usuario, identificador_empresa, datos_validados):
    """Crea una sucursal usando una ubicación aprobada para la empresa."""
    alcances = obtener_alcances_permiso(usuario, "sucursal.administrar")
    if not alcances.tiene_algun_alcance:
        raise PermissionDenied(
            'No tiene el permiso requerido: "sucursal.administrar".'
        )
    if not alcances.permite_todas_las_sucursales_de(identificador_empresa):
        raise Http404(
            "La empresa no existe o no está dentro de su alcance."
        )
    try:
        empresa = Empresa.objects.get(
            id=identificador_empresa,
            estado=EstadoOrganizacion.ACTIVO,
        )
    except (Empresa.DoesNotExist, ValueError) as error:
        raise Http404(
            "La empresa no existe, está inactiva o no está dentro de su alcance."
        ) from error

    datos = dict(datos_validados)
    ubicacion_id = datos.pop("ubicacion_id")
    try:
        relacion = UbicacionEmpresa.objects.select_related("ubicacion").get(
            empresa_id=empresa.id,
            ubicacion_id=ubicacion_id,
            estado=EstadoUbicacionEmpresa.APROBADO,
            ubicacion__estado=EstadoUbicacion.ACTIVO,
        )
    except (UbicacionEmpresa.DoesNotExist, ValueError) as error:
        raise ValidationError(
            {
                "ubicacion_id": (
                    "La ubicación no está activa y aprobada para esta empresa."
                )
            }
        ) from error

    codigo = datos.get("codigo")
    if codigo:
        codigo = codigo.strip().upper()
        if Sucursal.objects.filter(empresa=empresa, codigo=codigo).exists():
            raise ValidationError(
                {"codigo": "Ya existe una sucursal con este código en la empresa."}
            )
        datos["codigo"] = codigo
    else:
        datos["codigo"] = None

    sucursal = Sucursal.objects.create(
        empresa=empresa,
        ubicacion=relacion.ubicacion,
        estado=EstadoOrganizacion.ACTIVO,
        **datos,
    )
    return (
        Sucursal.objects.select_related(
            "empresa",
            "ubicacion",
            "ubicacion__tipo_ubicacion",
            "ubicacion__pais",
        ).get(pk=sucursal.pk)
    )
