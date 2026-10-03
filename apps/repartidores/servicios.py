"""Casos de uso transaccionales para administrar motoristas."""

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import Http404
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.flota.models import Vehiculo
from apps.flota.opciones import EstadoVehiculo, TipoVehiculo
from apps.organizaciones.models import Empresa
from apps.organizaciones.opciones import EstadoOrganizacion
from apps.repartidores.models import HistorialEstadoRepartidor, Repartidor
from apps.repartidores.capacidad import calcular_capacidad, contar_solicitudes_activas
from apps.repartidores.opciones import EstadoOperativoRepartidor
from apps.usuarios.models import RolUsuario, Usuario
from apps.usuarios.opciones import EstadoUsuario, TipoAlcanceRol
from apps.usuarios.servicios import obtener_alcances_permiso, usuario_tiene_permiso


def _obtener_empresa_activa(identificador):
    try:
        return Empresa.objects.get(
            id=identificador, estado=EstadoOrganizacion.ACTIVO
        )
    except (Empresa.DoesNotExist, ValueError) as error:
        raise Http404("La empresa no existe o está inactiva.") from error


def _obtener_usuario_activo(identificador):
    try:
        return Usuario.objetos.get(id=identificador, estado=EstadoUsuario.ACTIVO)
    except (Usuario.DoesNotExist, ValueError) as error:
        raise Http404("El usuario no existe o no está activo.") from error


def _validar_rol_repartidor(usuario_objetivo, empresa):
    filtros = {
        "usuario": usuario_objetivo,
        "activo": True,
        "rol__activo": True,
    }
    if settings.MODO_APLICACION == "CORPORATIVO":
        filtros.update(
            rol__codigo="REPARTIDOR_CORPORATIVO",
            tipo_alcance=TipoAlcanceRol.EMPRESA,
            empresa=empresa,
        )
    else:
        filtros.update(
            rol__codigo="REPARTIDOR_RED",
            tipo_alcance=TipoAlcanceRol.GLOBAL,
        )
    if not RolUsuario.objetos.filter(**filtros).exists():
        raise ValidationError(
            {"usuario_id": "El usuario no posee el rol de motorista requerido."}
        )


def _obtener_vehiculo_activo(identificador, empresa):
    if not identificador:
        return None
    try:
        return Vehiculo.objects.get(
            id=identificador,
            empresa=empresa,
            estado=EstadoVehiculo.ACTIVO,
            tipo=TipoVehiculo.MOTOCICLETA,
        )
    except (Vehiculo.DoesNotExist, ValueError) as error:
        raise Http404(
            "El vehículo no existe, no está activo o pertenece a otro alcance."
        ) from error


@transaction.atomic
def crear_repartidor(usuario, datos_validados):
    datos = dict(datos_validados)
    usuario_objetivo = _obtener_usuario_activo(datos.pop("usuario_id"))
    empresa_id = datos.pop("empresa_id", None)

    if settings.MODO_APLICACION == "CORPORATIVO":
        if not empresa_id:
            raise ValidationError(
                {"empresa_id": "La empresa es obligatoria en Corporate."}
            )
        empresa = _obtener_empresa_activa(empresa_id)
        autorizado = usuario_tiene_permiso(
            usuario, "repartidor.administrar", empresa=empresa
        )
        if usuario_objetivo.empresa_id != empresa.id:
            raise ValidationError(
                {"usuario_id": "El usuario no pertenece a la empresa indicada."}
            )
    else:
        if empresa_id:
            raise ValidationError(
                {"empresa_id": "Los motoristas de Network tienen alcance global."}
            )
        if usuario_objetivo.empresa_id is not None:
            raise ValidationError(
                {
                    "usuario_id": (
                        "El motorista de Network no puede pertenecer a una "
                        "empresa cliente."
                    )
                }
            )
        empresa = None
        autorizado = obtener_alcances_permiso(
            usuario, "repartidor.administrar"
        ).global_

    if not autorizado:
        raise PermissionDenied(
            'No tiene el permiso requerido: "repartidor.administrar".'
        )
    _validar_rol_repartidor(usuario_objetivo, empresa)
    vehiculo = _obtener_vehiculo_activo(datos.pop("vehiculo_id", None), empresa)

    try:
        return Repartidor.objects.create(
            usuario=usuario_objetivo,
            empresa=empresa,
            vehiculo=vehiculo,
        )
    except IntegrityError as error:
        raise ValidationError(
            {"usuario_id": "Este usuario ya posee un perfil de motorista."}
        ) from error


def _puede_administrar_repartidor(usuario, repartidor):
    if repartidor.empresa_id:
        return usuario_tiene_permiso(
            usuario,
            "repartidor.administrar",
            empresa=repartidor.empresa,
        )
    return obtener_alcances_permiso(usuario, "repartidor.administrar").global_


def _exigir_actualizacion_propia(usuario, repartidor, cambios):
    if usuario.pk != repartidor.usuario_id:
        return False
    if "estado_operativo" in cambios and not usuario_tiene_permiso(
        usuario,
        "repartidor.actualizar_estado",
        empresa=repartidor.empresa,
    ):
        raise PermissionDenied(
            'No tiene el permiso requerido: "repartidor.actualizar_estado".'
        )
    return True


@transaction.atomic
def actualizar_operacion_repartidor(usuario, identificador_repartidor, cambios):
    try:
        repartidor = (
            Repartidor.objects.select_for_update(of=("self",))
            .select_related("usuario", "empresa", "vehiculo")
            .get(id=identificador_repartidor, activo=True)
        )
    except (Repartidor.DoesNotExist, ValueError) as error:
        raise Http404("El motorista no existe o está inactivo.") from error

    cambios = dict(cambios)
    if "capacidad" in cambios:
        raise ValidationError(
            {"capacidad": "La capacidad se calcula automáticamente."}
        )
    motivo = cambios.pop("motivo", None)
    es_actualizacion_propia = _exigir_actualizacion_propia(
        usuario, repartidor, cambios
    )
    if not es_actualizacion_propia and not _puede_administrar_repartidor(
        usuario, repartidor
    ):
        raise PermissionDenied(
            'No tiene el permiso requerido: "repartidor.administrar".'
        )

    estado_anterior = repartidor.estado_operativo
    capacidad_anterior = repartidor.capacidad
    estado_nuevo = cambios.get("estado_operativo", estado_anterior)
    capacidad_nueva = calcular_capacidad(contar_solicitudes_activas(repartidor))

    if estado_nuevo == estado_anterior and capacidad_nueva == capacidad_anterior:
        raise ValidationError("La operación no contiene cambios efectivos.")
    if estado_nuevo == "AVAILABLE" and (
        not repartidor.vehiculo_id
        or repartidor.vehiculo.estado != EstadoVehiculo.ACTIVO
        or repartidor.vehiculo.tipo != TipoVehiculo.MOTOCICLETA
    ):
        raise ValidationError(
            {"estado_operativo": "Se requiere un vehículo activo para estar disponible."}
        )

    repartidor.estado_operativo = estado_nuevo
    repartidor.capacidad = capacidad_nueva
    repartidor.save(update_fields=("estado_operativo", "capacidad", "actualizado_en"))
    HistorialEstadoRepartidor.objects.create(
        repartidor=repartidor,
        estado_anterior=estado_anterior,
        estado_nuevo=estado_nuevo,
        capacidad_anterior=capacidad_anterior,
        capacidad_nueva=capacidad_nueva,
        realizado_por=usuario,
        motivo=motivo,
    )
    if (
        estado_nuevo == EstadoOperativoRepartidor.DISPONIBLE
        and estado_anterior != EstadoOperativoRepartidor.DISPONIBLE
    ):
        from apps.solicitudes.servicios import programar_reintento_pendientes

        programar_reintento_pendientes(repartidor.empresa_id)
    return repartidor
