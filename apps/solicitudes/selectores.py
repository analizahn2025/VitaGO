"""Consultas autorizadas y optimizadas del dominio de solicitudes."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Count, F, Q
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.organizaciones.models import Empresa, Sucursal
from apps.organizaciones.opciones import EstadoOrganizacion
from apps.solicitudes.excepciones import CreacionSolicitudNoDisponible
from apps.solicitudes.cobertura import comparten_departamento, departamento_normalizado
from apps.solicitudes.models import Solicitud, TipoServicio
from apps.solicitudes.opciones import EstadoSolicitud, ModalidadSolicitud
from apps.ubicaciones.models import UbicacionEmpresa
from apps.ubicaciones.opciones import EstadoUbicacion, EstadoUbicacionEmpresa
from apps.usuarios.servicios import (
    obtener_alcances_permiso,
    usuario_tiene_permiso,
)


def _filtro_por_alcances(alcances):
    if alcances.global_:
        return Q()
    return Q(empresa_id__in=alcances.empresas) | Q(
        sucursal_id__in=alcances.sucursales
    )


def _consulta_base_solicitudes():
    return Solicitud.objects.select_related(
        "empresa",
        "sucursal",
        "solicitada_por",
        "repartidor_asignado",
        "repartidor_asignado__usuario",
        "repartidor_asignado__vehiculo",
        "tipo_servicio",
        "origen",
        "destino",
    ).prefetch_related("movimientos_especiales__jornada")


def listar_tipos_servicio_autorizados(usuario):
    codigos = (
        "solicitud.crear",
        "solicitud.ver",
        "solicitud.ver_propias",
        "solicitud.ver_asignadas",
    )
    if not any(
        obtener_alcances_permiso(usuario, codigo).tiene_algun_alcance
        for codigo in codigos
    ):
        raise PermissionDenied(
            "No tiene permisos para consultar tipos de servicio."
        )
    return TipoServicio.objects.filter(activo=True).order_by("nombre", "id")


def _obtener_empresa_para_creacion(usuario, empresa_id):
    alcances = obtener_alcances_permiso(usuario, "solicitud.crear")
    if not alcances.tiene_algun_alcance:
        raise PermissionDenied(
            'No tiene el permiso requerido: "solicitud.crear".'
        )
    if not alcances.permite_empresa(empresa_id):
        raise Http404("La empresa no existe o no está dentro de su alcance.")
    try:
        empresa = Empresa.objects.get(
            id=empresa_id,
            estado=EstadoOrganizacion.ACTIVO,
        )
    except (Empresa.DoesNotExist, ValueError) as error:
        raise Http404(
            "La empresa no existe o no está dentro de su alcance."
        ) from error
    return empresa, alcances


def _sucursales_origen_autorizadas(
    empresa,
    alcances,
    sucursal_id=None,
):
    consulta = (
        Sucursal.objects.filter(
            empresa=empresa,
            estado=EstadoOrganizacion.ACTIVO,
            ubicacion__estado=EstadoUbicacion.ACTIVO,
            ubicacion__empresas_autorizadas__empresa=empresa,
            ubicacion__empresas_autorizadas__estado=(
                EstadoUbicacionEmpresa.APROBADO
            ),
            ubicacion__empresas_autorizadas__permite_origen=True,
        )
        .select_related("ubicacion", "ubicacion__tipo_ubicacion")
        .distinct()
    )
    if sucursal_id:
        if not alcances.permite_sucursal(sucursal_id, empresa.id):
            raise Http404(
                "La sucursal no existe o no está dentro de su alcance."
            )
        consulta = consulta.filter(id=sucursal_id)
        if not consulta.exists():
            raise Http404(
                "La sucursal no existe, está inactiva o no puede ser origen."
            )
    elif not (
        alcances.global_
        or empresa.id in alcances.empresas
    ):
        consulta = consulta.filter(id__in=alcances.sucursales)
    return consulta.order_by("nombre", "id")


def _convertir_sucursales_en_puntos(sucursales):
    return [
        {
            "sucursal_id": sucursal.id,
            "sucursal_nombre": sucursal.nombre,
            "ubicacion": sucursal.ubicacion,
        }
        for sucursal in sucursales
    ]


def obtener_opciones_creacion_solicitud(usuario, filtros):
    if settings.MODO_APLICACION == "EXTERNO":
        raise CreacionSolicitudNoDisponible()

    empresa, alcances = _obtener_empresa_para_creacion(
        usuario,
        filtros["empresa_id"],
    )
    sucursales_origen = _sucursales_origen_autorizadas(
        empresa,
        alcances,
        filtros.get("sucursal_id"),
    )
    origenes = _convertir_sucursales_en_puntos(sucursales_origen)
    puede_crear_especial = usuario_tiene_permiso(
        usuario,
        "solicitud.crear_envio_especial",
        empresa=empresa,
    )
    modalidades = [
        {
            "codigo": ModalidadSolicitud.ENTRE_SUCURSALES,
            "nombre": ModalidadSolicitud.ENTRE_SUCURSALES.label,
            "requiere_destino_registrado": True,
            "presentacion_ruta": "MAPA",
        },
        {
            "codigo": ModalidadSolicitud.EMPRESA_TRANSPORTE,
            "nombre": ModalidadSolicitud.EMPRESA_TRANSPORTE.label,
            "requiere_destino_registrado": True,
            "presentacion_ruta": "MAPA",
        },
    ]
    if puede_crear_especial:
        modalidades.append(
            {
                "codigo": ModalidadSolicitud.ESPECIAL,
                "nombre": ModalidadSolicitud.ESPECIAL.label,
                "requiere_destino_registrado": False,
                "presentacion_ruta": "SOLO_KILOMETROS",
            }
        )

    modalidad = filtros.get("modalidad")
    destinos = []
    mensaje_disponibilidad = None
    if modalidad == ModalidadSolicitud.ESPECIAL and not puede_crear_especial:
        raise PermissionDenied(
            "Solo el gerente de operaciones puede crear envíos especiales."
        )
    if modalidad == ModalidadSolicitud.ENTRE_SUCURSALES:
        origen_id = filtros.get("origen_id")
        sucursal_origen_id = filtros.get("sucursal_id")
        origen = next(
            (
                punto
                for punto in origenes
                if (
                    punto["ubicacion"].id == origen_id
                    or punto["sucursal_id"] == origen_id
                    or (
                        origen_id is None
                        and punto["sucursal_id"] == sucursal_origen_id
                    )
                )
            ),
            None,
        )
        if origen is None and (origen_id or sucursal_origen_id):
            raise Http404(
                "El origen no existe o no está dentro de su alcance."
            )
        if origen is not None:
            ubicacion_origen_id = origen["ubicacion"].id
            departamento = departamento_normalizado(origen["ubicacion"])
        else:
            ubicacion_origen_id = None
            departamento = ""
        if departamento:
            sucursales_destino = (
                Sucursal.objects.filter(
                    empresa=empresa,
                    estado=EstadoOrganizacion.ACTIVO,
                    ubicacion__estado=EstadoUbicacion.ACTIVO,
                    ubicacion__pais_id=origen["ubicacion"].pais_id,
                    ubicacion__empresas_autorizadas__empresa=empresa,
                    ubicacion__empresas_autorizadas__estado=(
                        EstadoUbicacionEmpresa.APROBADO
                    ),
                    ubicacion__empresas_autorizadas__permite_destino=True,
                )
                .exclude(ubicacion_id=ubicacion_origen_id)
                .select_related("ubicacion", "ubicacion__tipo_ubicacion")
                .distinct()
                .order_by("nombre", "id")
            )
            # Mismo comparador que el alta: los campos administrativos son texto
            # y pueden contener espacios/capitalización/Unicode equivalentes.
            destinos = _convertir_sucursales_en_puntos(
                sucursal for sucursal in sucursales_destino
                if comparten_departamento(origen["ubicacion"], sucursal.ubicacion)
            )
        if not origenes:
            mensaje_disponibilidad = (
                "No hay sucursales disponibles para crear solicitudes."
            )
        elif origen is not None and not departamento:
            mensaje_disponibilidad = (
                "La sucursal de origen no tiene departamento registrado. "
                "Solicite su actualización al administrador."
            )
        elif origen is not None and not destinos:
            mensaje_disponibilidad = (
                "No hay sucursales de destino disponibles en el mismo departamento."
            )
    elif modalidad == ModalidadSolicitud.EMPRESA_TRANSPORTE:
        relaciones = (
            UbicacionEmpresa.objects.filter(
                empresa=empresa,
                estado=EstadoUbicacionEmpresa.APROBADO,
                permite_destino=True,
                ubicacion__estado=EstadoUbicacion.ACTIVO,
                ubicacion__tipo_ubicacion__codigo="EMPRESA_TRANSPORTE",
                ubicacion__tipo_ubicacion__activo=True,
            )
            .select_related("ubicacion", "ubicacion__tipo_ubicacion")
            .order_by("ubicacion__nombre", "ubicacion_id")
        )
        destinos = [
            {
                "sucursal_id": None,
                "sucursal_nombre": None,
                "ubicacion": relacion.ubicacion,
            }
            for relacion in relaciones
        ]

    return {
        "empresa_id": empresa.id,
        "sucursal_id": filtros.get("sucursal_id"),
        "modalidad_seleccionada": modalidad,
        "puede_crear_envio_especial": puede_crear_especial,
        "modalidades": modalidades,
        "origenes": origenes,
        "destinos": destinos,
        "mensaje_disponibilidad": mensaje_disponibilidad,
    }


def listar_solicitudes_autorizadas(usuario, filtros=None):
    """Une visibilidad administrativa y propia sin ampliar alcances."""
    alcances_generales = obtener_alcances_permiso(usuario, "solicitud.ver")
    alcances_propios = obtener_alcances_permiso(
        usuario,
        "solicitud.ver_propias",
    )
    alcances_asignados = obtener_alcances_permiso(
        usuario,
        "solicitud.ver_asignadas",
    )
    if not any(
        (
            alcances_generales.tiene_algun_alcance,
            alcances_propios.tiene_algun_alcance,
            alcances_asignados.tiene_algun_alcance,
        )
    ):
        raise PermissionDenied(
            'No tiene el permiso requerido para consultar solicitudes.'
        )

    if alcances_generales.global_:
        filtro_visibilidad = Q()
    else:
        filtro_visibilidad = Q(pk__isnull=True)
        if alcances_generales.tiene_algun_alcance:
            filtro_visibilidad |= _filtro_por_alcances(alcances_generales)
        if alcances_propios.tiene_algun_alcance:
            filtro_visibilidad |= Q(
                _filtro_por_alcances(alcances_propios),
                solicitada_por_id=usuario.pk,
            )
        if alcances_asignados.tiene_algun_alcance:
            filtro_visibilidad |= Q(
                _filtro_por_alcances(alcances_asignados),
                repartidor_asignado__usuario_id=usuario.pk,
            )

    consulta = _consulta_base_solicitudes().filter(filtro_visibilidad).distinct()
    filtros = filtros or {}
    if filtros.get("empresa_id"):
        consulta = consulta.filter(empresa_id=filtros["empresa_id"])
    if filtros.get("sucursal_id"):
        consulta = consulta.filter(sucursal_id=filtros["sucursal_id"])
    if filtros.get("sin_sucursal"):
        consulta = consulta.filter(sucursal__isnull=True)
    if filtros.get("solicitada_por_id"):
        consulta = consulta.filter(
            solicitada_por_id=filtros["solicitada_por_id"]
        )
    if filtros.get("estado"):
        consulta = consulta.filter(estado=filtros["estado"])
    if filtros.get("prioridad"):
        consulta = consulta.filter(prioridad=filtros["prioridad"])
    if filtros.get("modalidad"):
        consulta = consulta.filter(modalidad=filtros["modalidad"])
    return consulta.order_by("-creado_en", "-id")


def agrupar_solicitudes_autorizadas(usuario, por, filtros=None):
    """Agrupa solamente solicitudes de alcance administrativo autorizado."""
    alcances = obtener_alcances_permiso(usuario, "solicitud.ver")
    if not alcances.tiene_algun_alcance:
        raise PermissionDenied(
            'No tiene el permiso requerido: "solicitud.ver".'
        )

    consulta = listar_solicitudes_autorizadas(usuario, filtros)
    if not alcances.global_:
        consulta = consulta.filter(_filtro_por_alcances(alcances))
    consulta = consulta.order_by()
    if por == "sucursal":
        return (
            consulta.values(
                "empresa_id",
                "sucursal_id",
                empresa_nombre=F("empresa__nombre"),
                sucursal_nombre=F("sucursal__nombre"),
            )
            .annotate(total=Count("id", distinct=True))
            .order_by("empresa_nombre", "sucursal_nombre", "sucursal_id")
        )
    if por == "solicitante":
        return (
            consulta.values(
                "empresa_id",
                "solicitada_por_id",
                empresa_nombre=F("empresa__nombre"),
                solicitante_nombres=F("solicitada_por__nombres"),
                solicitante_apellidos=F("solicitada_por__apellidos"),
            )
            .annotate(total=Count("id", distinct=True))
            .order_by(
                "empresa_nombre",
                "solicitante_nombres",
                "solicitante_apellidos",
                "solicitada_por_id",
            )
        )
    raise ValueError("La agrupación solicitada no es válida.")


def _resumir_consulta_solicitudes(consulta):
    pendientes = (EstadoSolicitud.PENDIENTE, EstadoSolicitud.ASIGNADA)
    activas = (
        EstadoSolicitud.HACIA_RECOLECCION,
        EstadoSolicitud.EN_RECOLECCION,
        EstadoSolicitud.RECOLECTADA,
        EstadoSolicitud.EN_TRANSITO,
        EstadoSolicitud.EN_DESTINO,
    )
    fallidas = (
        EstadoSolicitud.RECOLECCION_FALLIDA,
        EstadoSolicitud.ENTREGA_FALLIDA,
    )
    conteos = consulta.aggregate(
        total=Count("id", distinct=True),
        pendientes=Count(
            "id",
            filter=Q(estado__in=pendientes),
            distinct=True,
        ),
        activas=Count(
            "id",
            filter=Q(estado__in=activas),
            distinct=True,
        ),
        entregadas=Count(
            "id",
            filter=Q(estado=EstadoSolicitud.ENTREGADA),
            distinct=True,
        ),
        fallidas=Count(
            "id",
            filter=Q(estado__in=fallidas),
            distinct=True,
        ),
        canceladas=Count(
            "id",
            filter=Q(estado=EstadoSolicitud.CANCELADA),
            distinct=True,
        ),
    )
    return conteos, consulta[:5]


def resumir_solicitudes_autorizadas(usuario, filtros=None):
    consulta = listar_solicitudes_autorizadas(usuario, filtros)
    return _resumir_consulta_solicitudes(consulta)


def obtener_resumen_solicitante_autorizado(usuario, filtros=None):
    """Conserva acumulados y agrega entregas del día operativo solicitado."""
    filtros = filtros or {}
    consulta = listar_solicitudes_autorizadas(usuario, filtros)
    conteos, recientes = _resumir_consulta_solicitudes(consulta)
    zona = ZoneInfo(
        getattr(
            settings,
            "ZONA_HORARIA_RESUMEN_SOLICITANTE",
            "America/Tegucigalpa",
        )
    )
    fecha = filtros.get("fecha_operativa")
    if fecha is None:
        fecha = timezone.localdate(timezone.now(), timezone=zona)
    inicio = datetime.combine(fecha, time.min, tzinfo=zona)
    siguiente = datetime.combine(fecha + timedelta(days=1), time.min, tzinfo=zona)
    entregas_del_dia = consulta.filter(
        estado=EstadoSolicitud.ENTREGADA,
        entregada_en__gte=inicio,
        entregada_en__lt=siguiente,
    )
    return {
        **conteos,
        "recientes": recientes,
        "fecha_operativa": fecha.isoformat(),
        "zona_horaria_operativa": zona.key,
        "entregadas_del_dia": entregas_del_dia.count(),
        "entregas_recientes_del_dia": entregas_del_dia.order_by(
            "-entregada_en", "-id"
        )[:5],
    }


def obtener_solicitud_autorizada(usuario, identificador_solicitud):
    consulta = listar_solicitudes_autorizadas(usuario).prefetch_related(
        "articulos",
        "eventos",
        "asignaciones__repartidor__usuario",
        "asignaciones__repartidor__vehiculo",
    )
    try:
        return consulta.get(id=identificador_solicitud)
    except (Solicitud.DoesNotExist, ValueError) as error:
        raise Http404(
            "La solicitud no existe o no está dentro de su alcance."
        ) from error
