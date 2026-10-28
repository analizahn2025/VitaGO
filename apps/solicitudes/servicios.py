"""Casos de uso transaccionales para crear solicitudes."""

import logging
import uuid

from django.conf import settings
from django.db import transaction
from django.db.models import Q, Subquery
from django.core.exceptions import ValidationError as ValidacionModelo
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.flota.opciones import EstadoVehiculo, TipoVehiculo
from apps.solicitudes.asignacion_automatica import candidatos_ordenados
from apps.solicitudes.carga import validar_cantidad_tubos
from apps.solicitudes.cobertura import comparten_departamento, departamento_normalizado
from apps.organizaciones.models import Empresa, Sucursal
from apps.organizaciones.opciones import EstadoOrganizacion
from apps.solicitudes.excepciones import (
    CreacionSolicitudNoDisponible,
    LimiteSolicitudesRepartidor,
    CupoTubosInsuficiente,
)
from apps.solicitudes.models import (
    AsignacionSolicitud,
    ArticuloSolicitud,
    EventoSolicitud,
    MovimientoEnvioEspecial,
    Solicitud,
    TipoServicio,
)
from apps.solicitudes.opciones import (
    ESTADOS_SOLICITUD_ACTIVOS,
    EstadoAsignacionSolicitud,
    EstadoMovimientoEnvioEspecial,
    EstadoSolicitud,
    ModalidadSolicitud,
    PrioridadSolicitud,
    TipoAsignacionSolicitud,
    TipoEventoSolicitud,
)
from apps.ubicaciones.models import UbicacionEmpresa
from apps.ubicaciones.opciones import EstadoUbicacion, EstadoUbicacionEmpresa
from apps.repartidores.models import Repartidor
from apps.repartidores.limites import obtener_limites_repartidor
from apps.repartidores.operacion import registrar_operacion_repartidor
from apps.repartidores.capacidad import (
    contar_solicitudes_activas,
    sincronizar_capacidad_repartidor,
    obtener_carga_tubos,
)
from apps.repartidores.opciones import EstadoOperativoRepartidor
from apps.repartidores.habilitacion import roles_operativos_vigentes
from apps.usuarios.models import Usuario
from apps.usuarios.opciones import EstadoUsuario
from apps.usuarios.servicios import usuario_tiene_permiso
from apps.notificaciones.servicios import crear_notificaciones_asignacion


registro = logging.getLogger("vitago.api")
MAXIMO_ASIGNACIONES_POR_REINTENTO = 5


def _obtener_empresa_y_sucursal(empresa_id, sucursal_id):
    try:
        empresa = Empresa.objects.get(
            id=empresa_id,
            estado=EstadoOrganizacion.ACTIVO,
        )
    except (Empresa.DoesNotExist, ValueError) as error:
        raise Http404("La empresa no existe o está inactiva.") from error

    sucursal = None
    if sucursal_id:
        try:
            sucursal = Sucursal.objects.get(
                id=sucursal_id,
                empresa_id=empresa.id,
                estado=EstadoOrganizacion.ACTIVO,
            )
        except (Sucursal.DoesNotExist, ValueError) as error:
            raise Http404(
                "La sucursal no existe, está inactiva o pertenece a otra empresa."
            ) from error
    return empresa, sucursal


def _obtener_ubicacion_habilitada(
    empresa,
    ubicacion_id,
    campo_uso,
    mensaje,
):
    filtros = {
        "empresa": empresa,
        "ubicacion_id": ubicacion_id,
        "estado": EstadoUbicacionEmpresa.APROBADO,
        "ubicacion__estado": EstadoUbicacion.ACTIVO,
        campo_uso: True,
    }
    try:
        return UbicacionEmpresa.objects.select_related("ubicacion").get(
            **filtros
        ).ubicacion
    except (UbicacionEmpresa.DoesNotExist, ValueError) as error:
        raise Http404(mensaje) from error


def _generar_numero_solicitud(identificador):
    fecha = timezone.localdate().strftime("%Y%m%d")
    return f"SOL-{fecha}-{identificador.hex[:8].upper()}"


def _validar_origen_corporativo(empresa, sucursal, origen):
    if not Sucursal.objects.filter(
        empresa=empresa,
        ubicacion=origen,
        estado=EstadoOrganizacion.ACTIVO,
    ).exists():
        raise ValidationError(
            {"origen_id": "El origen debe ser una sucursal activa de la empresa."}
        )
    if sucursal is not None and sucursal.ubicacion_id != origen.id:
        raise ValidationError(
            {"sucursal_id": "La sucursal indicada debe coincidir con el origen."}
        )


def _validar_destino_corporativo(empresa, modalidad, origen, destino):
    if modalidad == ModalidadSolicitud.ENTRE_SUCURSALES:
        if destino.id == origen.id:
            raise ValidationError(
                {"destino_id": "El destino debe ser una sucursal diferente."}
            )
        if not Sucursal.objects.filter(
            empresa=empresa,
            ubicacion=destino,
            estado=EstadoOrganizacion.ACTIVO,
        ).exists():
            raise ValidationError(
                {"destino_id": "El destino debe ser otra sucursal activa."}
            )
        if not departamento_normalizado(origen):
            raise ValidationError({"origen_id": "La sucursal de origen no tiene departamento registrado."})
        if not comparten_departamento(origen, destino):
            raise ValidationError(
                {
                    "destino_id": (
                        "Los traslados entre sucursales deben permanecer en el "
                        "mismo país y departamento."
                    )
                }
            )
    elif modalidad == ModalidadSolicitud.EMPRESA_TRANSPORTE:
        if (
            destino.tipo_ubicacion.codigo != "EMPRESA_TRANSPORTE"
            or not destino.tipo_ubicacion.activo
        ):
            raise ValidationError(
                {
                    "destino_id": (
                        "El destino debe estar registrado como empresa de transporte."
                    )
                }
            )


@transaction.atomic
def crear_solicitud(usuario, datos_validados):
    if settings.MODO_APLICACION == "EXTERNO":
        raise CreacionSolicitudNoDisponible()

    datos = dict(datos_validados)
    validar_cantidad_tubos(datos.get("cantidad_tubos"))
    articulos_datos = datos.pop("articulos")
    empresa, sucursal = _obtener_empresa_y_sucursal(
        datos.pop("empresa_id"),
        datos.pop("sucursal_id", None),
    )
    if not usuario_tiene_permiso(
        usuario,
        "solicitud.crear",
        empresa=empresa,
        sucursal=sucursal,
    ):
        raise PermissionDenied(
            'No tiene el permiso requerido: "solicitud.crear" en este alcance.'
        )

    modalidad = datos.pop("modalidad", None)
    destino_especial = datos.pop("destino_especial", None)
    destino_id = datos.pop("destino_id", None)
    if not modalidad:
        raise ValidationError(
            {"modalidad": "Debe indicar la modalidad de la solicitud corporativa."}
        )
    if modalidad == ModalidadSolicitud.ABIERTO:
        raise ValidationError(
            {"modalidad": "La modalidad ABIERTA no está disponible en Corporate."}
        )
    if modalidad == ModalidadSolicitud.ESPECIAL:
        if destino_id is not None:
            raise ValidationError(
                {"destino_id": "Un envío especial no usa un destino registrado."}
            )
        destino_especial = (destino_especial or "").strip()
        if not destino_especial:
            raise ValidationError(
                {"destino_especial": "Debe describir el destino especial."}
            )
        if not usuario_tiene_permiso(
            usuario,
            "solicitud.crear_envio_especial",
            empresa=empresa,
        ):
            raise PermissionDenied(
                "Solo el gerente de operaciones puede crear envíos especiales."
            )
    else:
        if destino_id is None:
            raise ValidationError(
                {"destino_id": "Debe indicar el destino de la solicitud."}
            )
        if destino_especial is not None:
            raise ValidationError(
                {"destino_especial": "Solo aplica a envíos especiales."}
            )

    try:
        tipo_servicio = TipoServicio.objects.get(
            id=datos.pop("tipo_servicio_id"),
            activo=True,
        )
    except (TipoServicio.DoesNotExist, ValueError) as error:
        raise Http404("El tipo de servicio no existe o está inactivo.") from error

    origen = _obtener_ubicacion_habilitada(
        empresa,
        datos.pop("origen_id"),
        "permite_origen",
        "La ubicación de origen no está aprobada para esta empresa.",
    )
    _validar_origen_corporativo(empresa, sucursal, origen)
    destino = None
    if modalidad != ModalidadSolicitud.ESPECIAL:
        destino = _obtener_ubicacion_habilitada(
            empresa,
            destino_id,
            "permite_destino",
            "La ubicación de destino no está aprobada para esta empresa.",
        )
        _validar_destino_corporativo(empresa, modalidad, origen, destino)

    identificador = uuid.uuid4()
    solicitud = Solicitud.objects.create(
        id=identificador,
        numero=_generar_numero_solicitud(identificador),
        empresa=empresa,
        sucursal=sucursal,
        solicitada_por=usuario,
        tipo_servicio=tipo_servicio,
        modalidad=modalidad,
        origen=origen,
        destino=destino,
        destino_especial=(
            destino_especial if modalidad == ModalidadSolicitud.ESPECIAL else None
        ),
        estado=EstadoSolicitud.PENDIENTE,
        **datos,
    )
    articulos = [
        ArticuloSolicitud(solicitud=solicitud, **datos_articulo)
        for datos_articulo in articulos_datos
    ]
    for indice, articulo in enumerate(articulos):
        try:
            articulo.full_clean()
        except ValidacionModelo as error:
            detalles = [
                {"indice": indice, "campo": campo, "mensaje": mensaje}
                for campo, mensajes in error.message_dict.items()
                for mensaje in mensajes
            ]
            raise ValidationError({"articulos": detalles}) from error
    ArticuloSolicitud.objects.bulk_create(articulos)
    EventoSolicitud.objects.create(
        solicitud=solicitud,
        tipo=TipoEventoSolicitud.CREADA,
        realizado_por=usuario,
        metadatos={
            "estado": EstadoSolicitud.PENDIENTE,
            "prioridad": solicitud.prioridad,
            "modalidad": solicitud.modalidad,
        },
    )
    solicitud = _asignar_automaticamente(solicitud, usuario)
    if solicitud.estado == EstadoSolicitud.PENDIENTE:
        # Cubre la carrera en la que un motorista se habilita mientras
        # esta solicitud todavía no es visible para otros procesos.
        programar_reintento_pendientes(solicitud.empresa_id)
    return solicitud


def _validar_rol_operativo_repartidor(repartidor, empresa):
    if not roles_operativos_vigentes(repartidor.usuario_id, empresa.pk).exists():
        raise ValidationError(
            {"repartidor_id": "El usuario ya no posee el rol de motorista requerido."}
        )


def _validar_repartidor_disponible(repartidor, solicitud):
    from apps.solicitudes.vigencia import exigir_vigencia_solicitud, limite_dia_operativo

    exigir_vigencia_solicitud(solicitud)
    # Orden de bloqueo: solicitud -> motorista -> configuración compartida.
    limites = obtener_limites_repartidor(repartidor, bloquear=True)
    cantidad = contar_solicitudes_activas(repartidor)
    if cantidad >= limites["limite_solicitudes"]:
        raise LimiteSolicitudesRepartidor(limites["limite_solicitudes"])
    validar_cantidad_tubos(solicitud.cantidad_tubos)
    carga = obtener_carga_tubos(repartidor)
    if carga["solicitudes_sin_cantidad_tubos"]:
        raise CupoTubosInsuficiente("Debe completar la cantidad de tubos de las solicitudes activas del motorista.")
    disponibles = max(0, limites["limite_tubos"] - carga["tubos_comprometidos"])
    if solicitud.cantidad_tubos > disponibles:
        raise CupoTubosInsuficiente(f"El motorista dispone de {disponibles} tubos de cupo; la solicitud requiere {solicitud.cantidad_tubos}.")
    if not repartidor.activo or not Usuario.objetos.filter(pk=repartidor.usuario_id, estado=EstadoUsuario.ACTIVO).exists():
        raise ValidationError({"repartidor_id": "El motorista no está activo."})
    if settings.MODO_APLICACION == "CORPORATIVO":
        from apps.jornadas.models import JornadaRepartidor

        jornada = JornadaRepartidor.objects.filter(repartidor=repartidor, estado="ACTIVA").first()
        if jornada and timezone.now() >= limite_dia_operativo(jornada.iniciada_en, solicitud.empresa):
            raise ValidationError({"repartidor_id": "La jornada pertenece a un día operativo terminado."})
        if solicitud.reasignacion_pendiente and solicitud.estado in (
            EstadoSolicitud.RECOLECTADA, EstadoSolicitud.EN_TRANSITO, EstadoSolicitud.EN_DESTINO,
        ) and jornada is None:
            raise ValidationError({"repartidor_id": "Continuar una entrega requiere jornada activa."})
        if solicitud.reasignacion_pendiente and solicitud.modalidad == ModalidadSolicitud.ESPECIAL and solicitud.estado in (
            EstadoSolicitud.RECOLECTADA, EstadoSolicitud.EN_TRANSITO, EstadoSolicitud.EN_DESTINO,
        ) and (cantidad or jornada is None):
            raise ValidationError({"repartidor_id": "Continuar un especial requiere jornada activa y dedicación exclusiva."})
    if repartidor.estado_operativo not in (
        EstadoOperativoRepartidor.DISPONIBLE,
        EstadoOperativoRepartidor.EN_RUTA,
    ) or (
        repartidor.estado_operativo == EstadoOperativoRepartidor.EN_RUTA
        and not cantidad
    ):
        raise ValidationError({"repartidor_id": "El motorista no está disponible."})
    if (
        not repartidor.vehiculo_id
        or repartidor.vehiculo.estado != EstadoVehiculo.ACTIVO
        or repartidor.vehiculo.tipo != TipoVehiculo.MOTOCICLETA
    ):
        raise ValidationError(
            {"repartidor_id": "El motorista debe tener un vehículo activo."}
        )
    if settings.MODO_APLICACION == "CORPORATIVO":
        if repartidor.empresa_id != solicitud.empresa_id:
            raise ValidationError(
                {"repartidor_id": "El motorista pertenece a otra empresa."}
            )
    elif repartidor.empresa_id is not None:
        raise ValidationError(
            {"repartidor_id": "El motorista de Network debe tener alcance global."}
        )

    _validar_rol_operativo_repartidor(repartidor, solicitud.empresa)
    if MovimientoEnvioEspecial.objects.filter(
        repartidor=repartidor,
        estado=EstadoMovimientoEnvioEspecial.ACTIVO,
    ).exists():
        raise ValidationError(
            {"repartidor_id": "El motorista atiende un envío especial exclusivo."}
        )
    lleva_prioritaria = (
        Solicitud.objects.filter(
            repartidor_asignado=repartidor,
            prioridad=PrioridadSolicitud.PRIORITARIA,
            estado__in=ESTADOS_SOLICITUD_ACTIVOS,
        )
        .exclude(pk=solicitud.pk)
        .exists()
    )
    if lleva_prioritaria:
        raise ValidationError(
            {"repartidor_id": "El motorista tiene una solicitud prioritaria activa."}
        )


@transaction.atomic
def asignar_solicitud_manualmente(usuario, identificador_solicitud, datos_validados):
    try:
        solicitud = (
            # El UUID no cambia: excluir otras escrituras sin impedir que las
            # versiones de otra ruta referencien esta solicitud por FK.
            Solicitud.objects.select_for_update(of=("self",), no_key=True)
            .select_related("empresa", "sucursal", "repartidor_asignado")
            .get(id=identificador_solicitud)
        )
    except (Solicitud.DoesNotExist, ValueError) as error:
        raise Http404("La solicitud no existe.") from error

    if not (solicitud.reasignacion_pendiente and solicitud.estado in ESTADOS_SOLICITUD_ACTIVOS) and solicitud.estado not in (
        EstadoSolicitud.PENDIENTE,
        EstadoSolicitud.ASIGNADA,
    ):
        raise ValidationError(
            {"estado": "Solo se puede asignar una solicitud pendiente o asignada."}
        )

    es_reasignacion = solicitud.repartidor_asignado_id is not None
    permiso = "solicitud.reasignar" if es_reasignacion else "solicitud.asignar"
    if not usuario_tiene_permiso(
        usuario,
        permiso,
        empresa=solicitud.empresa,
        sucursal=solicitud.sucursal,
    ):
        raise PermissionDenied(f'No tiene el permiso requerido: "{permiso}".')

    ids_repartidores = {datos_validados["repartidor_id"]}
    if solicitud.repartidor_asignado_id:
        ids_repartidores.add(solicitud.repartidor_asignado_id)
    repartidores_bloqueados = {
        registro.id: registro
        for registro in Repartidor.objects.select_for_update(of=("self",))
        .select_related("usuario", "empresa", "vehiculo")
        .filter(id__in=ids_repartidores)
        .order_by("id")
    }
    repartidor = repartidores_bloqueados.get(datos_validados["repartidor_id"])
    if repartidor is None:
        raise Http404("El motorista no existe.")
    repartidor_anterior = repartidores_bloqueados.get(
        solicitud.repartidor_asignado_id
    )

    if solicitud.repartidor_asignado_id == repartidor.id:
        raise ValidationError(
            {"repartidor_id": "La solicitud ya está asignada a este motorista."}
        )
    _validar_repartidor_disponible(repartidor, solicitud)

    solicitud = _registrar_asignacion(
        solicitud,
        repartidor,
        usuario,
        tipo=TipoAsignacionSolicitud.MANUAL,
        motivo=datos_validados.get("motivo"),
        repartidor_anterior=repartidor_anterior,
    )
    if repartidor_anterior is not None:
        programar_reintento_pendientes(solicitud.empresa_id)
    return solicitud


def _registrar_asignacion(
    solicitud,
    repartidor,
    usuario,
    *,
    tipo,
    motivo=None,
    repartidor_anterior=None,
    distancia_gps_km=None,
):
    """Persiste asignación, auditoría, capacidad y aviso en una transacción."""
    es_contingencia = solicitud.reasignacion_pendiente
    estado_anterior = solicitud.estado
    es_reasignacion = repartidor_anterior is not None or es_contingencia
    asignacion_anterior = (
        AsignacionSolicitud.objects.select_for_update()
        .filter(solicitud=solicitud, estado=EstadoAsignacionSolicitud.ACTIVA)
        .first()
    )
    if es_reasignacion and not es_contingencia and asignacion_anterior is None:
        raise ValidationError(
            "La solicitud no posee una asignación activa consistente."
        )
    if not es_reasignacion and asignacion_anterior is not None:
        raise ValidationError(
            "La solicitud posee una asignación activa inconsistente."
        )

    ahora = timezone.now()
    if asignacion_anterior is not None:
        asignacion_anterior.estado = EstadoAsignacionSolicitud.REASIGNADA
        asignacion_anterior.finalizada_en = ahora
        asignacion_anterior.save(
            update_fields=("estado", "finalizada_en", "actualizado_en")
        )

    AsignacionSolicitud.objects.create(
        solicitud=solicitud,
        repartidor=repartidor,
        asignada_por=usuario,
        tipo=tipo,
        estado=EstadoAsignacionSolicitud.ACTIVA,
        asignada_en=ahora,
        aceptada_en=ahora if es_contingencia and estado_anterior in (
            EstadoSolicitud.RECOLECTADA, EstadoSolicitud.EN_TRANSITO, EstadoSolicitud.EN_DESTINO,
        ) else None,
        motivo=motivo,
    )
    repartidor_anterior_id = solicitud.repartidor_asignado_id
    if es_contingencia:
        repartidor_anterior_id = solicitud.asignaciones.filter(
            estado=EstadoAsignacionSolicitud.REASIGNADA,
        ).order_by("-finalizada_en", "-pk").values_list("repartidor_id", flat=True).first()
    solicitud.repartidor_asignado = repartidor
    continua_entrega = es_contingencia and estado_anterior in (
        EstadoSolicitud.RECOLECTADA, EstadoSolicitud.EN_TRANSITO, EstadoSolicitud.EN_DESTINO,
    )
    # Ya recogido: conservar la entrega, sin volver a pedir recolección.
    solicitud.estado = estado_anterior if continua_entrega else EstadoSolicitud.ASIGNADA
    if continua_entrega and estado_anterior == EstadoSolicitud.EN_DESTINO:
        # La llegada del motorista anterior permanece en sus eventos, pero no
        # acredita la del reemplazo. Este continúa directamente al destino.
        solicitud.estado = EstadoSolicitud.EN_TRANSITO
        solicitud.llegada_destino_en = None
    solicitud.reasignacion_pendiente = False
    solicitud.asignada_en = ahora
    solicitud.save(
        update_fields=(
            "repartidor_asignado", "estado", "asignada_en", "reasignacion_pendiente",
            "llegada_destino_en", "actualizado_en"
        )
    )

    metadatos = {
        "contingencia_suspension": es_contingencia,
        "continua_entrega": continua_entrega,
        "estado_anterior": estado_anterior,
        "estado_nuevo": solicitud.estado,
        "traspaso_fisico_fuera_app": continua_entrega,
        "repartidor_id": str(repartidor.id),
        "repartidor_anterior_id": (
            str(repartidor_anterior_id) if repartidor_anterior_id else None
        ),
        "tipo_asignacion": tipo,
    }
    if tipo == TipoAsignacionSolicitud.AUTOMATICA:
        metadatos["distancia_gps_linea_recta_km"] = (
            round(distancia_gps_km, 3) if distancia_gps_km is not None else None
        )
    evento = EventoSolicitud.objects.create(
        solicitud=solicitud,
        tipo=(
            TipoEventoSolicitud.REASIGNADA
            if es_reasignacion else TipoEventoSolicitud.ASIGNADA
        ),
        realizado_por=usuario,
        repartidor=repartidor,
        metadatos=metadatos,
    )
    sincronizar_capacidad_repartidor(
        repartidor, usuario, "Asignación de solicitud."
    )
    if continua_entrega:
        if solicitud.modalidad == ModalidadSolicitud.ESPECIAL:
            from apps.seguimiento.vigencia import posiciones_vigentes
            from apps.solicitudes.servicios_movimientos import iniciar_movimiento_especial

            posicion = posiciones_vigentes().filter(repartidor=repartidor).first()
            if posicion is None:
                raise ValidationError({"repartidor_id": "Se requiere GPS vigente para continuar un envío especial."})
            iniciar_movimiento_especial(solicitud, repartidor, latitud=posicion.latitud, longitud=posicion.longitud, ahora=ahora)
        registrar_operacion_repartidor(
            repartidor, usuario, estado_nuevo=EstadoOperativoRepartidor.EN_RUTA,
            motivo="Continuación de entrega por pérdida de habilitación del motorista anterior.",
        )
    if repartidor_anterior is not None:
        sincronizar_capacidad_repartidor(
            repartidor_anterior, usuario, "Reasignación de solicitud."
        )
        if (
            repartidor_anterior.estado_operativo == EstadoOperativoRepartidor.EN_RUTA
            and contar_solicitudes_activas(repartidor_anterior) == 0
        ):
            registrar_operacion_repartidor(
                repartidor_anterior,
                usuario,
                estado_nuevo=EstadoOperativoRepartidor.DISPONIBLE,
                motivo="El motorista quedó sin solicitudes activas.",
            )
    crear_notificaciones_asignacion(
        solicitud=solicitud,
        evento=evento,
        repartidor=repartidor,
        anterior=repartidor_anterior,
    )
    from apps.rutas.models import VersionRuta
    from apps.rutas.servicios import sincronizar_ruta

    if repartidor_anterior is not None:
        sincronizar_ruta(repartidor_anterior, VersionRuta.Motivo.REASIGNACION)
    sincronizar_ruta(
        repartidor,
        VersionRuta.Motivo.REASIGNACION if es_reasignacion
        else VersionRuta.Motivo.ASIGNACION,
    )
    from apps.solicitudes.flujo_automatico import programar_avance_automatico
    programar_avance_automatico(repartidor.pk)
    if repartidor_anterior is not None:
        programar_avance_automatico(repartidor_anterior.pk)
    return solicitud


def _asignar_automaticamente(solicitud, usuario):
    """Busca el candidato cercano y revalida su estado con la fila bloqueada."""
    for identificador, distancia in candidatos_ordenados(solicitud):
        repartidor = (
            Repartidor.objects.select_for_update(of=("self",), skip_locked=True)
            .select_related("usuario", "empresa", "vehiculo")
            .filter(id=identificador)
            .first()
        )
        if repartidor is None:
            continue
        try:
            _validar_repartidor_disponible(repartidor, solicitud)
        except (ValidationError, LimiteSolicitudesRepartidor, CupoTubosInsuficiente):
            continue
        from apps.seguimiento.vigencia import posiciones_vigentes

        if settings.ASIGNACION_REQUIERE_GPS_VIGENTE and not posiciones_vigentes().filter(repartidor=repartidor).exists():
            continue
        # La validación del tramo especial también necesita GPS, incluso
        # cuando se habilitó expresamente el fallback de asignación sin GPS.
        if solicitud.reasignacion_pendiente and solicitud.modalidad == ModalidadSolicitud.ESPECIAL and solicitud.estado in (
            EstadoSolicitud.RECOLECTADA, EstadoSolicitud.EN_TRANSITO, EstadoSolicitud.EN_DESTINO,
        ) and not posiciones_vigentes().filter(repartidor=repartidor).exists():
            continue
        return _registrar_asignacion(
            solicitud,
            repartidor,
            usuario,
            tipo=TipoAsignacionSolicitud.AUTOMATICA,
            motivo=(
                "Asignación automática por disponibilidad y cercanía GPS."
                if distancia is not None
                else "Asignación automática sin GPS registrado."
            ),
            distancia_gps_km=distancia,
        )
    return solicitud


@transaction.atomic
def _reintentar_primera_solicitud_pendiente(empresa_id, excluir_ids=()):
    """Bloquea la pendiente más antigua antes de buscar un motorista."""
    solicitud = (
        Solicitud.objects.select_for_update(of=("self",), skip_locked=True, no_key=True)
        .select_related("empresa", "origen", "solicitada_por")
        .filter(
            empresa_id=empresa_id,
            repartidor_asignado__isnull=True,
        )
        .filter(Q(estado=EstadoSolicitud.PENDIENTE) | Q(reasignacion_pendiente=True, estado__in=ESTADOS_SOLICITUD_ACTIVOS))
        .exclude(pk__in=excluir_ids)
        .filter(cantidad_tubos__isnull=False)
        .order_by("-reasignacion_pendiente", "creado_en", "id")
        .first()
    )
    if solicitud is None:
        return False, None
    from apps.solicitudes.vigencia import exigir_vigencia_solicitud
    try:
        exigir_vigencia_solicitud(solicitud)
    except ValidationError:
        from apps.solicitudes.contingencias import cerrar_solicitud_vencida
        cerrar_solicitud_vencida(solicitud.pk)
        return "CERRADA", solicitud.pk
    _asignar_automaticamente(solicitud, solicitud.solicitada_por)
    return solicitud.repartidor_asignado_id is not None, solicitud.pk


def reintentar_solicitudes_pendientes(empresa_id):
    """Procesa hasta un cupo de motorista por evento, sin procesos externos."""
    if settings.MODO_APLICACION != "CORPORATIVO" or empresa_id is None:
        return 0
    asignadas = 0
    examinadas = []
    for _ in range(50):
        resultado, solicitud_id = _reintentar_primera_solicitud_pendiente(empresa_id, examinadas)
        if solicitud_id is None:
            break
        examinadas.append(solicitud_id)
        if resultado is True:
            asignadas += 1
            if asignadas == MAXIMO_ASIGNACIONES_POR_REINTENTO:
                break
    return asignadas


def programar_reintento_pendientes(empresa_id):
    """Reintenta tras el commit para respetar el orden solicitud → motorista."""
    if settings.MODO_APLICACION != "CORPORATIVO" or empresa_id is None:
        return

    def reintentar_despues_del_commit():
        try:
            reintentar_solicitudes_pendientes(empresa_id)
        except Exception:
            registro.exception(
                "No se pudo reintentar la asignación de solicitudes pendientes."
            )

    transaction.on_commit(reintentar_despues_del_commit)


TRANSICIONES_PERMITIDAS = {
    EstadoSolicitud.PENDIENTE: {EstadoSolicitud.CANCELADA},
    EstadoSolicitud.ASIGNADA: {
        EstadoSolicitud.HACIA_RECOLECCION,
        EstadoSolicitud.CANCELADA,
    },
    EstadoSolicitud.HACIA_RECOLECCION: {
        EstadoSolicitud.EN_RECOLECCION,
        EstadoSolicitud.CANCELADA,
        EstadoSolicitud.RECOLECCION_FALLIDA,
    },
    EstadoSolicitud.EN_RECOLECCION: {
        EstadoSolicitud.RECOLECTADA,
        EstadoSolicitud.CANCELADA,
        EstadoSolicitud.RECOLECCION_FALLIDA,
    },
    EstadoSolicitud.RECOLECTADA: {
        EstadoSolicitud.EN_TRANSITO,
        EstadoSolicitud.ENTREGA_FALLIDA,
    },
    EstadoSolicitud.EN_TRANSITO: {
        EstadoSolicitud.EN_DESTINO,
        EstadoSolicitud.ENTREGA_FALLIDA,
    },
    EstadoSolicitud.EN_DESTINO: {
        EstadoSolicitud.ENTREGADA,
        EstadoSolicitud.ENTREGA_FALLIDA,
    },
}

TIPO_EVENTO_POR_ESTADO = {
    EstadoSolicitud.HACIA_RECOLECCION: TipoEventoSolicitud.HACIA_RECOLECCION,
    EstadoSolicitud.EN_RECOLECCION: TipoEventoSolicitud.LLEGADA_RECOLECCION,
    EstadoSolicitud.RECOLECTADA: TipoEventoSolicitud.RECOLECTADA,
    EstadoSolicitud.EN_TRANSITO: TipoEventoSolicitud.EN_TRANSITO,
    EstadoSolicitud.EN_DESTINO: TipoEventoSolicitud.LLEGADA_DESTINO,
    EstadoSolicitud.ENTREGADA: TipoEventoSolicitud.ENTREGADA,
    EstadoSolicitud.CANCELADA: TipoEventoSolicitud.CANCELADA,
    EstadoSolicitud.RECOLECCION_FALLIDA: (
        TipoEventoSolicitud.RECOLECCION_FALLIDA
    ),
    EstadoSolicitud.ENTREGA_FALLIDA: TipoEventoSolicitud.ENTREGA_FALLIDA,
}

ESTADOS_TERMINALES = {
    EstadoSolicitud.ENTREGADA,
    EstadoSolicitud.CANCELADA,
    EstadoSolicitud.RECOLECCION_FALLIDA,
    EstadoSolicitud.ENTREGA_FALLIDA,
}


def _obtener_repartidor_operativo(usuario, solicitud):
    if solicitud.repartidor_asignado_id is None:
        raise ValidationError(
            {"solicitud": "La solicitud no tiene un motorista asignado."}
        )
    try:
        repartidor = (
            Repartidor.objects.select_for_update(of=("self",))
            .select_related("usuario")
            .get(id=solicitud.repartidor_asignado_id, activo=True)
        )
    except Repartidor.DoesNotExist as error:
        raise ValidationError(
            {"solicitud": "El motorista asignado no posee un perfil activo."}
        ) from error
    if repartidor.usuario_id != usuario.pk:
        raise PermissionDenied(
            "Solo el motorista asignado puede realizar esta transición."
        )
    if not usuario_tiene_permiso(
        usuario,
        "solicitud.actualizar_estado",
        empresa=solicitud.empresa,
        sucursal=solicitud.sucursal,
    ):
        raise PermissionDenied(
            'No tiene el permiso requerido: "solicitud.actualizar_estado".'
        )
    return repartidor


def _cerrar_asignacion(solicitud, repartidor, usuario, estado_destino, ahora):
    asignacion = (
        AsignacionSolicitud.objects.select_for_update()
        .filter(
            solicitud=solicitud,
            estado=EstadoAsignacionSolicitud.ACTIVA,
        )
        .first()
    )
    if repartidor is not None and asignacion is None:
        raise ValidationError(
            "La solicitud no posee una asignación activa consistente."
        )
    if asignacion is not None:
        asignacion.estado = (
            EstadoAsignacionSolicitud.FINALIZADA
            if estado_destino == EstadoSolicitud.ENTREGADA
            else EstadoAsignacionSolicitud.CANCELADA
        )
        asignacion.finalizada_en = ahora
        asignacion.save(
            update_fields=("estado", "finalizada_en", "actualizado_en")
        )

    if repartidor is None:
        return
    tiene_otras_asignaciones = AsignacionSolicitud.objects.filter(
        repartidor=repartidor,
        estado=EstadoAsignacionSolicitud.ACTIVA,
    ).exclude(solicitud=solicitud).exists()
    admite_asignaciones = repartidor.estado_operativo in (
        EstadoOperativoRepartidor.DISPONIBLE,
        EstadoOperativoRepartidor.EN_RUTA,
    )
    # Cerrar un servicio no debe levantar una pausa ni una suspensión operativa.
    if admite_asignaciones and tiene_otras_asignaciones:
        registrar_operacion_repartidor(
            repartidor,
            usuario,
            estado_nuevo=EstadoOperativoRepartidor.EN_RUTA,
            motivo="La solicitud terminó; conserva otras asignaciones activas.",
        )
    elif admite_asignaciones:
        registrar_operacion_repartidor(
            repartidor,
            usuario,
            estado_nuevo=EstadoOperativoRepartidor.DISPONIBLE,
            motivo="La solicitud operativa finalizó.",
        )
    sincronizar_capacidad_repartidor(
        repartidor, usuario, "Cierre de solicitud."
    )


@transaction.atomic
def cambiar_estado_solicitud(usuario, identificador_solicitud, datos_validados, *, llegada_gps=None, automatismo=None):
    try:
        solicitud = (
            Solicitud.objects.select_for_update(of=("self",), no_key=True)
            .select_related("empresa", "sucursal", "repartidor_asignado")
            .get(id=identificador_solicitud)
        )
    except (Solicitud.DoesNotExist, ValueError) as error:
        raise Http404("La solicitud no existe.") from error

    from apps.solicitudes.vigencia import exigir_vigencia_solicitud
    exigir_vigencia_solicitud(solicitud)
    estado_destino = datos_validados["estado_destino"]
    if estado_destino in {
        EstadoSolicitud.CANCELADA,
        EstadoSolicitud.RECOLECCION_FALLIDA,
        EstadoSolicitud.ENTREGA_FALLIDA,
    } and not (datos_validados.get("motivo") or "").strip():
        raise ValidationError(
            {"motivo": "Debe indicar el motivo de esta transición."}
        )
    tiene_latitud = datos_validados.get("latitud") is not None
    tiene_longitud = datos_validados.get("longitud") is not None
    if tiene_latitud != tiene_longitud:
        raise ValidationError(
            "La latitud y longitud deben enviarse juntas."
        )
    if estado_destino not in TRANSICIONES_PERMITIDAS.get(solicitud.estado, set()):
        raise ValidationError(
            {
                "estado_destino": (
                    f"No se permite cambiar de {solicitud.estado} a "
                    f"{estado_destino}."
                )
            }
        )

    repartidor = None
    if estado_destino == EstadoSolicitud.CANCELADA:
        if not usuario_tiene_permiso(
            usuario,
            "solicitud.cancelar",
            empresa=solicitud.empresa,
            sucursal=solicitud.sucursal,
        ):
            raise PermissionDenied(
                'No tiene el permiso requerido: "solicitud.cancelar".'
            )
        if solicitud.repartidor_asignado_id:
            repartidor = Repartidor.objects.select_for_update(
                of=("self",)
            ).get(id=solicitud.repartidor_asignado_id)
    else:
        repartidor = _obtener_repartidor_operativo(usuario, solicitud)
        from apps.jornadas.models import JornadaRepartidor
        from apps.jornadas.opciones import EstadoJornada

        if not JornadaRepartidor.objects.select_for_update(of=("self",)).filter(
            repartidor=repartidor, estado=EstadoJornada.ACTIVA,
        ).exists():
            raise ValidationError(
                {"jornada": "Debe iniciar una jornada antes de operar la solicitud."}
            )
        exclusiva = Solicitud.objects.filter(
            repartidor_asignado=repartidor,
            prioridad=PrioridadSolicitud.PRIORITARIA,
            estado__in=(EstadoSolicitud.RECOLECTADA, EstadoSolicitud.EN_TRANSITO, EstadoSolicitud.EN_DESTINO),
        ).exclude(pk=solicitud.pk).exists()
        if exclusiva:
            raise ValidationError({"estado_destino": "Debe finalizar el envío prioritario recogido antes de operar otra solicitud."})

        if estado_destino in {
            EstadoSolicitud.HACIA_RECOLECCION, EstadoSolicitud.EN_RECOLECCION,
            EstadoSolicitud.RECOLECTADA, EstadoSolicitud.EN_TRANSITO,
            EstadoSolicitud.EN_DESTINO, EstadoSolicitud.ENTREGADA,
        }:
            from apps.solicitudes.flujo_automatico import exigir_siguiente_parada
            tipo_parada = (
                "RECOLECCION" if estado_destino in {
                    EstadoSolicitud.HACIA_RECOLECCION, EstadoSolicitud.EN_RECOLECCION,
                    EstadoSolicitud.RECOLECTADA,
                } else "ENVIO_ESPECIAL" if solicitud.modalidad == ModalidadSolicitud.ESPECIAL else "ENTREGA"
            )
            exigir_siguiente_parada(solicitud, repartidor, tipo_parada)

    if (
        settings.LLEGADAS_AUTOMATICAS_HABILITADAS
        and estado_destino in {EstadoSolicitud.EN_RECOLECCION, EstadoSolicitud.EN_DESTINO}
        and llegada_gps is None
        and not (
            estado_destino == EstadoSolicitud.EN_DESTINO
            and solicitud.modalidad == ModalidadSolicitud.ESPECIAL
            and solicitud.destino_id is None
        )
    ):
        # La prueba GPS solo la produce el detector interno bajo los bloqueos
        # operativos; nunca se toma de datos enviados por el dispositivo.
        raise ValidationError({
            "estado_destino": (
                "La llegada se registra automáticamente mediante GPS en la próxima "
                "parada. Mantenga el seguimiento activo y espere la detección."
            ),
        })

    if estado_destino == EstadoSolicitud.RECOLECTADA:
        validar_cantidad_tubos(solicitud.cantidad_tubos)
        from apps.evidencias.models import EvidenciaSolicitud
        from apps.evidencias.opciones import TipoEvidenciaSolicitud

        if not EvidenciaSolicitud.objects.filter(
            solicitud=solicitud,
            repartidor=repartidor,
            tipo=TipoEvidenciaSolicitud.FOTO_RECOLECCION,
            temperatura_contenedor_c__isnull=False,
            fuente_temperatura__in=("MANUAL", "AUTOMATICA"),
            capturada_en__gte=Subquery(AsignacionSolicitud.objects.filter(
                solicitud=solicitud, repartidor=repartidor, estado=EstadoAsignacionSolicitud.ACTIVA,
            ).values("asignada_en")[:1]),
        ).exists():
            raise ValidationError(
                {"evidencia": "Debe registrar la fotografía de recolección y la temperatura del contenedor."}
            )
    if estado_destino == EstadoSolicitud.ENTREGADA:
        from apps.evidencias.models import EvidenciaSolicitud
        from apps.evidencias.opciones import TipoEvidenciaSolicitud

        if not EvidenciaSolicitud.objects.filter(
            solicitud=solicitud,
            repartidor=repartidor,
            tipo=TipoEvidenciaSolicitud.FOTO_ENTREGA,
        ).exists():
            raise ValidationError(
                {"evidencia": "Debe registrar la fotografía de entrega."}
            )

    ahora = timezone.now()
    estado_anterior = solicitud.estado
    solicitud.estado = estado_destino
    campos_actualizados = ["estado", "actualizado_en"]
    if estado_destino in ESTADOS_TERMINALES:
        solicitud.reasignacion_pendiente = False
        solicitud.cerrada_en = ahora
        campos_actualizados += ["reasignacion_pendiente", "cerrada_en"]
    campo_fecha = {
        EstadoSolicitud.EN_RECOLECCION: "llegada_recoleccion_en",
        EstadoSolicitud.RECOLECTADA: "recolectada_en",
        EstadoSolicitud.EN_DESTINO: "llegada_destino_en",
        EstadoSolicitud.ENTREGADA: "entregada_en",
        EstadoSolicitud.CANCELADA: "cancelada_en",
    }.get(estado_destino)
    if campo_fecha:
        setattr(solicitud, campo_fecha, ahora)
        campos_actualizados.append(campo_fecha)
    solicitud.save(update_fields=campos_actualizados)

    es_envio_especial = solicitud.modalidad == ModalidadSolicitud.ESPECIAL
    if es_envio_especial and estado_destino == EstadoSolicitud.RECOLECTADA:
        from apps.solicitudes.servicios_movimientos import (
            iniciar_movimiento_especial,
        )

        iniciar_movimiento_especial(
            solicitud,
            repartidor,
            latitud=datos_validados.get("latitud"),
            longitud=datos_validados.get("longitud"),
            ahora=ahora,
        )
        registrar_operacion_repartidor(
            repartidor,
            usuario,
            estado_nuevo=EstadoOperativoRepartidor.EN_RUTA,
            motivo="El motorista inició un envío especial exclusivo.",
        )

    if es_envio_especial and estado_destino in {
        EstadoSolicitud.ENTREGADA,
        EstadoSolicitud.ENTREGA_FALLIDA,
    }:
        from apps.solicitudes.servicios_movimientos import (
            cerrar_movimiento_especial,
        )

        cerrar_movimiento_especial(
            solicitud,
            repartidor,
            latitud=datos_validados.get("latitud"),
            longitud=datos_validados.get("longitud"),
            ahora=ahora,
            sesiones_gps=datos_validados.get("sesiones_gps"),
        )

    if estado_destino == EstadoSolicitud.HACIA_RECOLECCION:
        registrar_operacion_repartidor(
            repartidor,
            usuario,
            estado_nuevo=EstadoOperativoRepartidor.EN_RUTA,
            motivo="El motorista inició el desplazamiento hacia la recolección.",
        )
        asignacion = AsignacionSolicitud.objects.select_for_update().get(
            solicitud=solicitud,
            estado=EstadoAsignacionSolicitud.ACTIVA,
        )
        if asignacion.aceptada_en is None:
            asignacion.aceptada_en = ahora
            asignacion.save(update_fields=("aceptada_en", "actualizado_en"))

    if estado_destino in ESTADOS_TERMINALES:
        _cerrar_asignacion(
            solicitud,
            repartidor,
            usuario,
            estado_destino,
            ahora,
        )

    metadatos = {
        "estado_anterior": estado_anterior,
        "estado_nuevo": estado_destino,
    }
    if datos_validados.get("motivo"):
        metadatos["motivo"] = datos_validados["motivo"]
    if llegada_gps is not None:
        metadatos["llegada_gps"] = llegada_gps
    if automatismo is not None:
        metadatos["automatismo"] = automatismo
    EventoSolicitud.objects.create(
        solicitud=solicitud,
        tipo=TIPO_EVENTO_POR_ESTADO[estado_destino],
        realizado_por=usuario,
        repartidor=repartidor,
        latitud=datos_validados.get("latitud"),
        longitud=datos_validados.get("longitud"),
        metadatos=metadatos,
    )
    if repartidor is not None:
        from apps.rutas.models import VersionRuta
        from apps.rutas.servicios import sincronizar_ruta

        sincronizar_ruta(
            repartidor,
            VersionRuta.Motivo.CANCELACION
            if estado_destino == EstadoSolicitud.CANCELADA
            else VersionRuta.Motivo.CAMBIO_ESTADO,
        )
    if (estado_destino in ESTADOS_TERMINALES or estado_destino == EstadoSolicitud.RECOLECTADA) and repartidor is not None:
        from apps.solicitudes.flujo_automatico import programar_avance_automatico
        programar_avance_automatico(repartidor.pk)
    if estado_destino in ESTADOS_TERMINALES and repartidor is not None:
        programar_reintento_pendientes(solicitud.empresa_id)
    return solicitud
