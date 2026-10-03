"""Casos de uso transaccionales del dominio de flota."""

from django.conf import settings
from django.core.exceptions import ValidationError as ValidacionDjango
from django.db import IntegrityError, transaction
from django.http import Http404
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.flota.models import Vehiculo
from apps.flota.opciones import TipoVehiculo
from apps.organizaciones.models import Empresa
from apps.organizaciones.opciones import EstadoOrganizacion
from apps.usuarios.servicios import obtener_alcances_permiso, usuario_tiene_permiso


def _obtener_empresa_activa(identificador):
    try:
        return Empresa.objects.get(
            id=identificador,
            estado=EstadoOrganizacion.ACTIVO,
        )
    except (Empresa.DoesNotExist, ValueError) as error:
        raise Http404("La empresa no existe o está inactiva.") from error


@transaction.atomic
def crear_vehiculo(usuario, datos_validados):
    datos = dict(datos_validados)
    if datos.get("tipo") != TipoVehiculo.MOTOCICLETA:
        raise ValidationError({"tipo": "Solo se pueden crear motocicletas."})
    if "capacidad_carga_kg" in datos:
        raise ValidationError(
            {"capacidad_carga_kg": "Este campo es obsoleto y no editable."}
        )
    empresa_id = datos.pop("empresa_id", None)

    if settings.MODO_APLICACION == "CORPORATIVO":
        if not empresa_id:
            raise ValidationError(
                {"empresa_id": "La empresa es obligatoria en Corporate."}
            )
        empresa = _obtener_empresa_activa(empresa_id)
        autorizado = usuario_tiene_permiso(
            usuario,
            "vehiculo.administrar",
            empresa=empresa,
        )
    else:
        if empresa_id:
            raise ValidationError(
                {"empresa_id": "Los vehículos de Network tienen alcance global."}
            )
        empresa = None
        autorizado = obtener_alcances_permiso(
            usuario, "vehiculo.administrar"
        ).global_

    if not autorizado:
        raise PermissionDenied(
            'No tiene el permiso requerido: "vehiculo.administrar".'
        )

    vehiculo = Vehiculo(empresa=empresa, **datos)
    try:
        vehiculo.full_clean()
        vehiculo.save()
    except ValidacionDjango as error:
        raise ValidationError(error.message_dict) from error
    except IntegrityError as error:
        raise ValidationError({"placa": "Ya existe un vehículo con esta placa."}) from error
    return vehiculo
