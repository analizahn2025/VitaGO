"""Operaciones transaccionales del dominio de ubicaciones."""

from django.db import transaction
from django.http import Http404
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.geografia.models import Pais
from apps.organizaciones.models import Empresa
from apps.organizaciones.opciones import EstadoOrganizacion
from apps.ubicaciones.models import TipoUbicacion, Ubicacion, UbicacionEmpresa
from apps.ubicaciones.opciones import EstadoUbicacion, EstadoUbicacionEmpresa
from apps.usuarios.servicios import (
    obtener_alcances_permiso,
    usuario_tiene_permiso,
)


def _obtener_empresa_administrable(usuario, identificador_empresa, permiso):
    alcances = obtener_alcances_permiso(usuario, permiso)
    if not alcances.tiene_algun_alcance:
        raise PermissionDenied(f'No tiene el permiso requerido: "{permiso}".')
    if not alcances.permite_todas_las_sucursales_de(identificador_empresa):
        raise Http404(
            "La empresa no existe o no está dentro de su alcance."
        )
    try:
        return Empresa.objects.get(
            id=identificador_empresa,
            estado=EstadoOrganizacion.ACTIVO,
        )
    except (Empresa.DoesNotExist, ValueError) as error:
        raise Http404(
            "La empresa no existe, está inactiva o no está dentro de su alcance."
        ) from error


@transaction.atomic
def registrar_ubicacion(usuario, datos_validados):
    """Registra una ubicación y su relación inicial con una empresa."""
    datos = dict(datos_validados)
    identificador_empresa = datos.pop("empresa_id")
    identificador_tipo = datos.pop("tipo_ubicacion_id")
    identificador_pais = datos.pop("pais_id")
    permite_origen = datos.pop("permite_origen")
    permite_destino = datos.pop("permite_destino")
    empresa = _obtener_empresa_administrable(
        usuario,
        identificador_empresa,
        "ubicacion.crear",
    )

    try:
        tipo_ubicacion = TipoUbicacion.objects.get(
            id=identificador_tipo,
            activo=True,
        )
    except (TipoUbicacion.DoesNotExist, ValueError) as error:
        raise ValidationError(
            {"tipo_ubicacion_id": "El tipo de ubicación no existe o está inactivo."}
        ) from error
    try:
        pais = Pais.objects.get(id=identificador_pais, activo=True)
    except (Pais.DoesNotExist, ValueError) as error:
        raise ValidationError(
            {"pais_id": "El país no existe o está inactivo."}
        ) from error

    identificador_google = datos.get("identificador_lugar_google")
    if identificador_google and Ubicacion.objects.filter(
        identificador_lugar_google=identificador_google
    ).exists():
        raise ValidationError(
            {
                "identificador_lugar_google": (
                    "Ya existe una ubicación con este identificador de Google."
                )
            }
        )

    ubicacion = Ubicacion.objects.create(
        **datos,
        tipo_ubicacion=tipo_ubicacion,
        pais=pais,
        verificada=False,
        estado=EstadoUbicacion.ACTIVO,
        creada_por=usuario.pk,
    )
    puede_aprobar = usuario_tiene_permiso(
        usuario,
        "ubicacion.aprobar",
        empresa=empresa,
    )
    relacion = UbicacionEmpresa.objects.create(
        empresa=empresa,
        ubicacion=ubicacion,
        permite_origen=permite_origen,
        permite_destino=permite_destino,
        estado=(
            EstadoUbicacionEmpresa.APROBADO
            if puede_aprobar
            else EstadoUbicacionEmpresa.PENDIENTE
        ),
    )
    return (
        UbicacionEmpresa.objects.select_related(
            "empresa",
            "ubicacion",
            "ubicacion__tipo_ubicacion",
            "ubicacion__pais",
        ).get(pk=relacion.pk)
    )


@transaction.atomic
def actualizar_autorizacion_ubicacion(
    usuario,
    identificador_ubicacion,
    identificador_empresa,
    cambios,
):
    """Actualiza el uso permitido de una ubicación dentro de una empresa."""
    empresa = _obtener_empresa_administrable(
        usuario,
        identificador_empresa,
        "ubicacion.aprobar",
    )
    try:
        relacion = (
            UbicacionEmpresa.objects.select_for_update()
            .select_related(
                "empresa",
                "ubicacion",
                "ubicacion__tipo_ubicacion",
                "ubicacion__pais",
            )
            .get(
                empresa_id=empresa.id,
                ubicacion_id=identificador_ubicacion,
            )
        )
    except (UbicacionEmpresa.DoesNotExist, ValueError) as error:
        raise Http404(
            "La autorización de ubicación no existe o no está dentro de su alcance."
        ) from error

    permite_origen = cambios.get("permite_origen", relacion.permite_origen)
    permite_destino = cambios.get("permite_destino", relacion.permite_destino)
    estado = cambios.get("estado", relacion.estado)
    if (
        estado == EstadoUbicacionEmpresa.APROBADO
        and not permite_origen
        and not permite_destino
    ):
        raise ValidationError(
            "Una ubicación aprobada debe permitir origen, destino o ambos."
        )

    for campo, valor in cambios.items():
        setattr(relacion, campo, valor)
    relacion.save(update_fields=(*cambios.keys(), "actualizado_en"))
    return relacion
