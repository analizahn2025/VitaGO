"""Reportes diarios de administración: agregados acotados a una página autorizada."""

from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.db.models import Avg, Case, Count, Exists, F, Max, Min, OuterRef, Q, Subquery, Sum, UUIDField, When, Window
from django.db.models.functions import RowNumber
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.evidencias.models import EvidenciaSolicitud
from apps.jornadas.models import JornadaRepartidor
from apps.repartidores.capacidad import calcular_capacidad, obtener_carga_tubos, puede_recibir_solicitudes
from apps.repartidores.limites import obtener_limites_repartidor
from apps.repartidores.models import Repartidor
from apps.repartidores.selectores import listar_repartidores_autorizados
from apps.solicitudes.models import AsignacionSolicitud, Solicitud
from apps.usuarios.servicios import obtener_alcances_permiso


def listar_motoristas_para_resumen(usuario, filtros):
    consulta = listar_repartidores_autorizados(usuario, filtros)
    # Un permiso de sucursal no habilita el historial completo de un motorista.
    # En Network, empresa_id=null requiere alcance global en todos los permisos.
    for codigo in ("repartidor.ver", "reporte.ver", "solicitud.ver", "jornada.ver", "evidencia.ver"):
        alcances = obtener_alcances_permiso(usuario, codigo)
        if not alcances.tiene_algun_alcance:
            raise PermissionDenied(f'No tiene el permiso requerido: "{codigo}".')
        if not alcances.global_:
            consulta = consulta.filter(empresa_id__in=alcances.empresas)
    if filtros.get("repartidor_id"):
        consulta = consulta.filter(pk=filtros["repartidor_id"])
    return consulta.select_related("empresa__pais")


def obtener_motorista_para_resumen(usuario, identificador, filtros):
    try:
        return listar_motoristas_para_resumen(usuario, filtros).get(pk=identificador)
    except Repartidor.DoesNotExist as error:
        raise Http404("El motorista no existe o no está dentro de su alcance.") from error


def periodo_operativo(repartidor, fecha, ahora):
    try:
        zona = ZoneInfo(repartidor.empresa.pais.zona_horaria_predeterminada if repartidor.empresa_id else settings.TIME_ZONE)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValidationError({"zona_horaria_operativa": "Debe corregir la zona horaria operativa configurada."}) from error
    fecha = fecha or timezone.localdate(ahora, timezone=zona)
    inicio = datetime.combine(fecha, time.min, tzinfo=zona)
    fin = datetime.combine(fecha + timedelta(days=1), time.min, tzinfo=zona)
    return fecha, zona, inicio, fin


def lecturas_temperatura(repartidores, inicio, fin):
    return EvidenciaSolicitud.objects.filter(
        repartidor_id__in=repartidores, tipo="FOTO_RECOLECCION",
        capturada_en__gte=inicio, capturada_en__lt=fin,
    ).order_by("-capturada_en", "-id")


def _lectura(lectura):
    return {
        "id": lectura.pk, "solicitud_id": lectura.solicitud_id,
        "numero_solicitud": lectura.solicitud.numero,
        "temperatura_contenedor_c": _decimal(lectura.temperatura_contenedor_c),
        "fuente_temperatura": lectura.fuente_temperatura,
        "capturada_en": lectura.capturada_en,
    }


def _decimal(valor, lugares="0.01"):
    return format(Decimal(valor).quantize(Decimal(lugares), rounding=ROUND_HALF_UP), "f") if valor is not None else None


def _actividad_por_fecha(identificadores, campo, inicio, fin, *, estados=None):
    historial = AsignacionSolicitud.objects.filter(solicitud_id=OuterRef("pk"))
    vigente = Q(finalizada_en__isnull=True) | Q(finalizada_en__gt=OuterRef(campo))
    if campo == "entregada_en":
        vigente |= Q(estado="FINALIZADA", finalizada_en=OuterRef(campo))
    if campo == "cerrada_en":
        vigente |= Q(estado="CANCELADA", finalizada_en=OuterRef(campo))
    responsable = historial.filter(asignada_en__lte=OuterRef(campo)).filter(vigente).order_by("-asignada_en", "-id")
    periodo = Q(**{f"{campo}__gte": inicio, f"{campo}__lt": fin})
    if campo == "cerrada_en":
        # El corte efectivo FIN_DIA es la medianoche que termina esa operación,
        # aunque la tarea de recuperación se ejecute durante el día siguiente.
        periodo = (periodo & ~Q(motivo_cierre="FIN_DIA")) | Q(
            motivo_cierre="FIN_DIA", cerrada_en__gt=inicio, cerrada_en__lte=fin,
        )
    consulta = Solicitud.objects.filter(periodo)
    if estados:
        consulta = consulta.filter(estado__in=estados)
    consulta = consulta.annotate(responsable=Case(
        When(Exists(historial), then=Subquery(responsable.values("repartidor_id")[:1])),
        default=F("repartidor_asignado_id"), output_field=UUIDField(),
    )).filter(responsable__in=identificadores).order_by()
    return {fila["responsable"]: fila for fila in consulta.values("responsable").annotate(
        cantidad=Count("id"), tubos=Sum("cantidad_tubos"),
        sin_cantidad=Count("id", filter=Q(cantidad_tubos__isnull=True)),
    )}


def _resumen_grupo(motoristas, inicio, fin, ahora):
    ids = [r.pk for r in motoristas]
    asignadas = {f["repartidor_id"]: f["cantidad"] for f in AsignacionSolicitud.objects.filter(
        repartidor_id__in=ids, asignada_en__gte=inicio, asignada_en__lt=fin,
    ).order_by().values("repartidor_id").annotate(cantidad=Count("solicitud_id", distinct=True))}
    recogidas = _actividad_por_fecha(ids, "recolectada_en", inicio, fin)
    entregadas = _actividad_por_fecha(ids, "entregada_en", inicio, fin, estados=("DELIVERED",))
    fallidas = _actividad_por_fecha(ids, "cerrada_en", inicio, fin, estados=("PICKUP_FAILED", "DELIVERY_FAILED"))
    canceladas = _actividad_por_fecha(ids, "cerrada_en", inicio, fin, estados=("CANCELLED",))
    medicion = Q(kilometraje_disponible=True)
    consolidada = medicion & Q(calidad_kilometraje__estado="CONSOLIDADO")
    jornadas = {f["repartidor_id"]: f for f in JornadaRepartidor.objects.filter(
        repartidor_id__in=ids, estado="FINALIZADA", iniciada_en__lt=fin, finalizada_en__gt=inicio, finalizada_en__lte=fin,
    ).order_by().values("repartidor_id").annotate(
        cerradas=Count("id"), con_medicion=Count("id", filter=medicion),
        consolidadas=Count("id", filter=consolidada),
        kilometros=Sum("kilometros_operativos", filter=medicion),
        kilometros_consolidados=Sum("kilometros_operativos", filter=consolidada),
    )}
    activas = {f["repartidor_id"]: f["cantidad"] for f in JornadaRepartidor.objects.filter(
        repartidor_id__in=ids, iniciada_en__lt=fin,
    ).filter(Q(finalizada_en__isnull=True) | Q(finalizada_en__gt=fin)).filter(
        Q(finalizada_en__isnull=True) | Q(finalizada_en__gt=inicio),
    ).order_by().values("repartidor_id").annotate(cantidad=Count("id"))} if inicio <= ahora else {}
    lecturas = lecturas_temperatura(ids, inicio, fin)
    temperaturas = {f["repartidor_id"]: f for f in lecturas.order_by().values("repartidor_id").annotate(
        registradas=Count("id"), con_temperatura=Count("temperatura_contenedor_c"),
        minima=Min("temperatura_contenedor_c"), maxima=Max("temperatura_contenedor_c"), promedio=Avg("temperatura_contenedor_c"),
    )}
    ultimas = defaultdict(list)
    for lectura in lecturas.select_related("solicitud").annotate(posicion=Window(
        RowNumber(), partition_by=[F("repartidor_id")], order_by=[F("capturada_en").desc(), F("id").desc()],
    )).filter(posicion__lte=5):
        ultimas[lectura.repartidor_id].append(_lectura(lectura))
    resultados = {}
    for r in motoristas:
        recogida, entrega = recogidas.get(r.pk, {}), entregadas.get(r.pk, {})
        km, temp = jornadas.get(r.pk, {}), temperaturas.get(r.pk, {})
        carga = obtener_carga_tubos(r)
        limites = obtener_limites_repartidor(r)
        incompletas = carga["solicitudes_sin_cantidad_tubos"]
        resultados[r.pk] = {
            "solicitudes": {"asignadas": asignadas.get(r.pk, 0), "recolectadas": recogida.get("cantidad", 0),
                            "entregadas": entrega.get("cantidad", 0), "fallidas": fallidas.get(r.pk, {}).get("cantidad", 0),
                            "canceladas": canceladas.get(r.pk, {}).get("cantidad", 0)},
            "tubos": {"recogidos_conocidos": recogida.get("tubos") or 0, "entregados_conocidos": entrega.get("tubos") or 0,
                      "recolecciones_sin_cantidad": recogida.get("sin_cantidad", 0), "entregas_sin_cantidad": entrega.get("sin_cantidad", 0)},
            "kilometraje": {"criterio": "CIERRE_JORNADA", "jornadas_cerradas": km.get("cerradas", 0),
                "jornadas_con_medicion": km.get("con_medicion", 0), "jornadas_consolidadas": km.get("consolidadas", 0),
                "jornadas_sin_cierre_en_periodo": activas.get(r.pk, 0),
                "kilometros_medidos": _decimal(km.get("kilometros"), "0.001"),
                "kilometros_consolidados": _decimal(km.get("kilometros_consolidados"), "0.001"),
                "completo": bool(km.get("cerradas")) and km.get("cerradas") == km.get("consolidadas") and not activas.get(r.pk)},
            "temperaturas": {"lecturas_registradas": temp.get("registradas", 0),
                "lecturas_con_temperatura": temp.get("con_temperatura", 0),
                "lecturas_sin_temperatura": temp.get("registradas", 0) - temp.get("con_temperatura", 0),
                "minima_c": _decimal(temp.get("minima")), "maxima_c": _decimal(temp.get("maxima")),
                "promedio_c": _decimal(temp.get("promedio")), "ultimas_lecturas": ultimas[r.pk]},
            "carga_actual": {**carga, **limites,
                "tubos_reservados": carga["tubos_comprometidos"] - carga["tubos_en_transporte"],
                "tubos_disponibles": 0 if incompletas else max(0, limites["limite_tubos"] - carga["tubos_comprometidos"]),
                "capacidad": calcular_capacidad(carga["solicitudes_activas"], **limites, **carga),
                "estado_operativo": r.estado_operativo, "puede_recibir_solicitudes": puede_recibir_solicitudes(r, carga["solicitudes_activas"], carga=carga)},
        }
    return resultados


def construir_resumenes(motoristas, fecha=None, *, ahora=None):
    ahora = ahora or timezone.now()
    grupos, periodos = defaultdict(list), {}
    for r in motoristas:
        periodos[r.pk] = periodo_operativo(r, fecha, ahora)
        grupos[periodos[r.pk][2:]].append(r)
    metricas = {}
    for (inicio, fin), grupo in grupos.items():
        metricas.update(_resumen_grupo(grupo, inicio, fin, ahora))
    resultados = []
    for r in motoristas:
        fecha_local, zona, inicio, fin = periodos[r.pk]
        resultados.append({
            "repartidor": {"id": r.pk, "nombres": r.usuario.nombres, "apellidos": r.usuario.apellidos,
                "activo": r.activo, "empresa_id": r.empresa_id, "empresa_nombre": r.empresa.nombre if r.empresa_id else None},
            "fecha_operativa": fecha_local.isoformat(), "zona_horaria_operativa": zona.key,
            "periodo": {"desde": inicio.isoformat(), "hasta_exclusivo": fin.isoformat()},
            "generado_en": ahora, **metricas[r.pk],
        })
    return resultados
