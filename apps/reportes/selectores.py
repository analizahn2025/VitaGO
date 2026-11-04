"""Reporte autorizado: datos propios, orden por motorista y detalles cronológicos."""

from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.evidencias.models import EvidenciaSolicitud
from apps.jornadas.models import JornadaRepartidor
from apps.repartidores.resumenes import construir_resumenes, listar_motoristas_para_resumen
from apps.seguimiento.models import DesviacionRuta
from apps.solicitudes.models import AsignacionSolicitud


LIMITE_MOTORISTAS = 200
LIMITE_FILAS = 5000
NOTA_REPORTE = (
    "Kilómetros operativos medidos por GPS propio, sin sumar por cada solicitud. "
    "N/D indica una medición ausente, pendiente o una jornada sin cierre. "
    "Los kilómetros consolidados son los confirmados por el control de sincronización GPS. "
    "La comparación histórica con Google está pendiente y no se calcula al descargar."
)


def _consulta_periodos(modelo, grupos, inicio, fin=None):
    condicion = Q(pk__in=[])
    for (desde, hasta), ids in grupos.items():
        periodo = Q(repartidor_id__in=ids, **{f"{inicio}__lt": hasta})
        periodo &= (Q(**{f"{fin}__isnull": True}) | Q(**{f"{fin}__gte": desde})) if fin else Q(**{f"{inicio}__gte": desde})
        condicion |= periodo
    return modelo.objects.filter(condicion)


def _acotar(consulta, disponibles):
    filas = list(consulta[:disponibles + 1])
    if len(filas) > disponibles:
        raise ValidationError({"fecha_desde": "El reporte supera 5000 filas de detalle. Reduzca el período o elija un motorista."})
    return filas


def construir_reporte_motoristas(usuario, filtros, *, ahora=None):
    ahora = ahora or timezone.now()
    desde = filtros.get("fecha_desde") or timezone.localdate(ahora)
    hasta = filtros.get("fecha_hasta") or desde
    consulta = listar_motoristas_para_resumen(usuario, filtros)
    motoristas = list(consulta[:LIMITE_MOTORISTAS + 1])
    if len(motoristas) > LIMITE_MOTORISTAS:
        raise ValidationError({"repartidor_id": "Seleccione una empresa o motorista: el reporte admite hasta 200 motoristas."})
    resumenes = construir_resumenes(motoristas, desde, fecha_hasta=hasta, ahora=ahora)
    grupos, entradas = defaultdict(list), {}
    for repartidor, resumen in zip(motoristas, resumenes):
        inicio = datetime.fromisoformat(resumen["periodo"]["desde"])
        fin = datetime.fromisoformat(resumen["periodo"]["hasta_exclusivo"])
        grupos[inicio, fin].append(repartidor.pk)
        entradas[repartidor.pk] = {
            "id": str(repartidor.pk), "nombre": f"{repartidor.usuario.nombres} {repartidor.usuario.apellidos}".strip(),
            "empresa": repartidor.empresa.nombre if repartidor.empresa_id else "Network - flota compartida",
            "placa": repartidor.vehiculo.placa if repartidor.vehiculo_id else None,
            "activo": repartidor.activo, "zona": resumen["zona_horaria_operativa"], "resumen": resumen,
            "jornadas": [], "servicios": [], "temperaturas": [], "desviaciones": [],
        }
    restantes = LIMITE_FILAS
    jornadas = _acotar(_consulta_periodos(JornadaRepartidor, grupos, "iniciada_en", "finalizada_en")
        .only("repartidor_id", "fecha_operativa", "iniciada_en", "finalizada_en", "estado",
              "kilometros_operativos", "kilometraje_disponible", "calidad_kilometraje",
              "minutos_activos", "minutos_operativos", "servicios_completados")
        .prefetch_related("almuerzos").order_by("iniciada_en", "id"), restantes)
    restantes -= len(jornadas)
    for jornada in jornadas:
        entrada = entradas[jornada.repartidor_id]
        minutos_almuerzo = sum(max(0, ((a.finalizada_en or min(ahora, jornada.finalizada_en or ahora)) - a.iniciada_en).total_seconds()) / 60
                              for a in jornada.almuerzos.all())
        cerrada = jornada.estado == "FINALIZADA"
        entrada["jornadas"].append({
            "fecha": jornada.fecha_operativa or timezone.localdate(jornada.iniciada_en, ZoneInfo(entrada["zona"])),
            "inicio": jornada.iniciada_en, "fin": jornada.finalizada_en, "estado": jornada.estado,
            "km": jornada.kilometros_operativos if cerrada and jornada.kilometraje_disponible else None,
            "calidad": jornada.calidad_kilometraje.get("estado", "SIN_VERIFICAR") if cerrada else "PENDIENTE_CIERRE",
            "minutos_activos": jornada.minutos_activos if cerrada else None,
            "minutos_operativos": jornada.minutos_operativos if cerrada else None,
            "minutos_almuerzo": round(minutos_almuerzo, 2),
            "entregas": jornada.servicios_completados if cerrada else None,
        })
    asignaciones = _acotar(_consulta_periodos(AsignacionSolicitud, grupos, "asignada_en", "finalizada_en")
        .select_related("solicitud__solicitada_por", "solicitud__sucursal", "solicitud__empresa", "solicitud__origen", "solicitud__destino")
        .only("repartidor_id", "solicitud_id", "asignada_en", "finalizada_en", "estado",
              "solicitud__numero", "solicitud__cantidad_tubos", "solicitud__cantidad_frascos",
              "solicitud__solicitada_por_id", "solicitud__solicitada_por__nombres", "solicitud__solicitada_por__apellidos",
              "solicitud__sucursal_id", "solicitud__sucursal__nombre", "solicitud__empresa_id", "solicitud__empresa__nombre",
              "solicitud__origen_id", "solicitud__origen__nombre", "solicitud__destino_id", "solicitud__destino__nombre",
              "solicitud__destino_especial", "solicitud__prioridad", "solicitud__modalidad", "solicitud__estado")
        .order_by("asignada_en", "id"), restantes)
    restantes -= len(asignaciones)
    for asignacion in asignaciones:
        solicitud = asignacion.solicitud
        entradas[asignacion.repartidor_id]["servicios"].append({
            "numero": solicitud.numero, "empresa": solicitud.empresa.nombre,
            "sucursal": solicitud.sucursal.nombre if solicitud.sucursal_id else None,
            "solicitante": f"{solicitud.solicitada_por.nombres} {solicitud.solicitada_por.apellidos}".strip(),
            "origen": solicitud.origen.nombre, "destino": solicitud.destino.nombre if solicitud.destino_id else solicitud.destino_especial,
            "prioridad": solicitud.get_prioridad_display(), "modalidad": solicitud.get_modalidad_display(),
            "estado_actual": solicitud.get_estado_display(), "estado_asignacion": asignacion.get_estado_display(),
            "asignada": asignacion.asignada_en, "fin_asignacion": asignacion.finalizada_en,
            "tubos": solicitud.cantidad_tubos, "frascos": solicitud.cantidad_frascos,
        })
    lecturas = _acotar(_consulta_periodos(EvidenciaSolicitud, grupos, "capturada_en")
        .filter(tipo="FOTO_RECOLECCION").select_related("solicitud")
        .only("repartidor_id", "solicitud_id", "solicitud__numero", "capturada_en", "temperatura_contenedor_c", "fuente_temperatura")
        .order_by("capturada_en", "id"), restantes)
    restantes -= len(lecturas)
    for lectura in lecturas:
        entradas[lectura.repartidor_id]["temperaturas"].append({
            "solicitud": lectura.solicitud.numero, "fecha": lectura.capturada_en,
            "temperatura": lectura.temperatura_contenedor_c, "fuente": lectura.fuente_temperatura,
        })
    alertas = _acotar(_consulta_periodos(DesviacionRuta, grupos, "detectada_en")
        .select_related("solicitud").only("repartidor_id", "solicitud_id", "solicitud__numero",
            "tipo_parada", "detectada_en", "finalizada_en", "motivo_cierre").order_by("detectada_en", "id"), restantes)
    for alerta in alertas:
        entradas[alerta.repartidor_id]["desviaciones"].append({
            "solicitud": alerta.solicitud.numero, "etapa": alerta.get_tipo_parada_display(),
            "detectada": alerta.detectada_en, "fin": alerta.finalizada_en, "motivo_cierre": alerta.motivo_cierre,
        })
    return {"fecha_desde": desde, "fecha_hasta": hasta, "generado_en": ahora,
            "nota": NOTA_REPORTE, "motoristas": list(entradas.values())}
