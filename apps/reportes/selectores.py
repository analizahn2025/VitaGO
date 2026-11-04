"""Resumen por período y detalle diario; solo datos autorizados, sin proveedores."""

from collections import defaultdict

from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.repartidores.resumenes import construir_resumenes, listar_motoristas_para_resumen, periodo_operativo
from apps.solicitudes.models import AsignacionSolicitud


LIMITE_MOTORISTAS = 200
LIMITE_FILAS = 5000
NOTA_RESUMEN = (
    "Km GPS por jornada, sin duplicarlos por envío. * Medición parcial o pendiente de consolidar. "
    "N/D: sin medición. Temperatura: promedio de lecturas de recolección del período."
)
NOTA_SERVICIOS = (
    "Asignaciones que estuvieron vigentes durante el día operativo; estados actuales al descargar. "
    "Una reasignación figura en el tramo de cada motorista. Horas en la zona operativa de su empresa."
)


def _motoristas_autorizados(usuario, filtros):
    motoristas = list(listar_motoristas_para_resumen(usuario, filtros)[:LIMITE_MOTORISTAS + 1])
    if len(motoristas) > LIMITE_MOTORISTAS:
        raise ValidationError({"repartidor_id": "Seleccione una empresa o motorista: el reporte admite hasta 200 motoristas."})
    return motoristas


def _identidad(repartidor):
    return {
        "id": str(repartidor.pk), "nombre": f"{repartidor.usuario.nombres} {repartidor.usuario.apellidos}".strip(),
        "empresa": repartidor.empresa.nombre if repartidor.empresa_id else "Network - flota compartida",
        "placa": repartidor.vehiculo.placa if repartidor.vehiculo_id else None,
    }


def construir_reporte_motoristas(usuario, filtros, *, ahora=None):
    ahora = ahora or timezone.now()
    desde, hasta = filtros["fecha_desde"], filtros["fecha_hasta"]
    motoristas = _motoristas_autorizados(usuario, filtros)
    resumenes = construir_resumenes(motoristas, desde, fecha_hasta=hasta, ahora=ahora, incluir_lecturas=False)
    etiqueta = f'Mensual · {filtros["mes"]}' if filtros["periodo"] == "MENSUAL" else f'Quincena {filtros["quincena"]} · {filtros["mes"]}'
    entradas = [{**_identidad(r), "zona": resumen["zona_horaria_operativa"], "resumen": resumen}
                for r, resumen in zip(motoristas, resumenes)]
    return {"tipo": "motoristas", "periodo": filtros["periodo"], "mes": filtros["mes"],
            "quincena": filtros.get("quincena"), "etiqueta": etiqueta,
            "fecha_desde": desde, "fecha_hasta": hasta, "generado_en": ahora,
            "nota": NOTA_RESUMEN, "motoristas": entradas}


def construir_reporte_servicios(usuario, filtros, *, ahora=None):
    ahora = ahora or timezone.now()
    motoristas = _motoristas_autorizados(usuario, filtros)
    grupos, entradas = defaultdict(list), {}
    for r in motoristas:
        _, zona, inicio, fin = periodo_operativo(r, filtros["fecha"], ahora)
        grupos[inicio, fin].append(r.pk)
        entradas[r.pk] = {**_identidad(r), "zona": zona.key, "servicios": []}
    condicion = Q(pk__in=[])
    for (inicio, fin), ids in grupos.items():
        condicion |= Q(repartidor_id__in=ids, asignada_en__lt=fin) & (
            Q(finalizada_en__isnull=True) | Q(finalizada_en__gt=inicio))
    asignaciones = list(AsignacionSolicitud.objects.filter(condicion)
        .select_related("solicitud__empresa", "solicitud__origen", "solicitud__destino")
        .only("repartidor_id", "solicitud_id", "asignada_en", "finalizada_en", "estado",
              "solicitud__numero", "solicitud__cantidad_tubos", "solicitud__cantidad_frascos",
              "solicitud__empresa_id", "solicitud__empresa__nombre", "solicitud__origen_id", "solicitud__origen__nombre",
              "solicitud__destino_id", "solicitud__destino__nombre", "solicitud__destino_especial", "solicitud__estado")
        .order_by("asignada_en", "id")[:LIMITE_FILAS + 1])
    if len(asignaciones) > LIMITE_FILAS:
        raise ValidationError({"fecha": "El día supera 5000 asignaciones. Seleccione una empresa o motorista."})
    for a in asignaciones:
        s = a.solicitud
        entradas[a.repartidor_id]["servicios"].append({
            "numero": s.numero, "empresa": s.empresa.nombre, "origen": s.origen.nombre,
            "destino": s.destino.nombre if s.destino_id else s.destino_especial,
            "estado_actual": s.get_estado_display(), "estado_asignacion": a.get_estado_display(),
            "asignada": a.asignada_en, "fin_asignacion": a.finalizada_en,
            "tubos": s.cantidad_tubos, "frascos": s.cantidad_frascos,
        })
    return {"tipo": "servicios", "etiqueta": f'Servicios · {filtros["fecha"].isoformat()}',
            "fecha_desde": filtros["fecha"], "fecha_hasta": filtros["fecha"], "generado_en": ahora,
            "nota": NOTA_SERVICIOS, "motoristas": list(entradas.values())}
