"""Cálculo explícito, acotado e idempotente. Ninguna lectura consulta Google.

La llamada HTTP se ejecuta fuera de la transacción de reserva. Un intento
fallido también consume presupuesto: no sabemos si Google llegó a facturarlo.
"""

from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied

from apps.repartidores.models import Repartidor
from apps.rutas.models import CalculoRutaVial, ConsumoRutasGoogle, RutaRepartidor, VersionRuta
from apps.rutas.proveedor_google import AVISO_MOTOCICLETA, ErrorProveedorGoogle, calcular_ruta_google
from apps.rutas.selectores import _obtener_repartidor_propio, obtener_paradas_operativas
from apps.rutas.servicios import sincronizar_ruta
from apps.rutas.tramos import destinos_unicos, presentar_tramos, tiene_desglose
from apps.seguimiento.vigencia import posiciones_vigentes
from apps.solicitudes.opciones import PrioridadSolicitud
from apps.usuarios.servicios import usuario_tiene_permiso


class ErrorRutaVial(APIException):
    def __init__(self, codigo, mensaje, estado=409):
        self.status_code = estado
        super().__init__({"codigo": codigo, "detail": mensaje})


def paradas_cartografiables(paradas):
    """Un especial detiene el trazado; un prioritario recogido se entrega directo."""
    elegidas = []
    for parada in paradas:
        if parada["presentacion_ruta"] != "MAPA" or not parada["ubicacion"]:
            break
        elegidas.append(parada)
        if parada["prioridad"] == PrioridadSolicitud.PRIORITARIA and parada["tipo"] == "ENTREGA":
            break
    return elegidas


def firma_paradas(paradas):
    return [{
        "solicitud_id": str(p["solicitud_id"]), "tipo": p["tipo"],
        "ubicacion_id": str(p["ubicacion"].id),
        "latitud": str(p["ubicacion"].latitud), "longitud": str(p["ubicacion"].longitud),
    } for p in paradas_cartografiables(paradas)]


def _es_sufijo(actual, anterior):
    return bool(actual) and len(actual) <= len(anterior) and actual == anterior[-len(actual):]


def calculo_reutilizable(ruta, firma, ahora):
    if not ruta or not firma:
        return None
    # A lo sumo veinte candidatos recientes; no se recupera contenido vencido.
    candidatos = CalculoRutaVial.objects.filter(
        version__ruta=ruta, estado=CalculoRutaVial.Estado.CALCULADA,
        expira_en__gt=ahora,
    ).exclude(polilinea_codificada="").select_related("version").order_by("-version__numero")[:20]
    return next((c for c in candidatos if _es_sufijo(firma, c.paradas_calculadas)), None)


def limpiar_geometria_vencida(ahora=None):
    return CalculoRutaVial.objects.filter(
        expira_en__lte=ahora or timezone.now(),
    ).exclude(polilinea_codificada="", polilineas_tramos=[]).update(
        polilinea_codificada="", polilineas_tramos=[],
    )


def presentar_ruta_vial(ruta, paradas, version_actual, *, calculo=None, metricas=None):
    ahora = timezone.now()
    firma = firma_paradas(paradas)
    disponible = calculo or calculo_reutilizable(ruta, firma, ahora)
    reutilizable = bool(disponible and disponible.estado == CalculoRutaVial.Estado.CALCULADA
                        and disponible.expira_en and disponible.expira_en > ahora
                        and disponible.polilinea_codificada
                        and _es_sufijo(firma, disponible.paradas_calculadas))
    if reutilizable:
        estado = "CALCULADA"
    elif not paradas:
        estado = "SIN_PARADAS"
    elif not firma:
        estado = "SOLO_KILOMETROS"
    else:
        if not disponible and ruta:
            disponible = CalculoRutaVial.objects.filter(version__ruta=ruta, version__numero=version_actual).first()
        estado = disponible.estado if disponible else "PENDIENTE"
        if disponible and disponible.estado == "CALCULADA":
            estado = "VENCIDA" if disponible.expira_en <= ahora else "ITINERARIO_CAMBIO"
        if not disponible and (not settings.HABILITAR_RUTAS_GOOGLE or not settings.CLAVE_API_GOOGLE_MAPS):
            estado = "NO_CONFIGURADA"
    interrumpido = bool(disponible and disponible.estado == "CALCULANDO" and
                       disponible.iniciada_en <= ahora - timedelta(seconds=max(60, settings.RUTAS_GOOGLE_TIMEOUT_SEGUNDOS * 3)))
    if interrumpido and estado == "CALCULANDO":
        estado = "FALLIDA"
    return {
        "estado": estado, "proveedor": "GOOGLE_MAPS", "atribucion": "Google Maps" if reutilizable else None,
        "aviso_motocicleta": AVISO_MOTOCICLETA,
        "version_actual": version_actual,
        "version_calculada": disponible.version.numero if disponible else None,
        "polilinea_codificada": disponible.polilinea_codificada if reutilizable else None,
        "incluye_tramos_completados": bool(reutilizable and firma != disponible.paradas_calculadas),
        "calculada_en": disponible.calculada_en if disponible else None,
        "expira_en": disponible.expira_en if disponible else None,
        "origen_gps": disponible.origen_gps if reutilizable else None,
        "codigo_error": "INTENTO_INTERRUPPIDO" if interrumpido else (disponible.codigo_error if disponible else None),
        "reintento_desde": disponible.iniciada_en + timedelta(seconds=60) if interrumpido else (disponible.reintento_desde if disponible else None),
        "metricas_en_respuesta": bool(reutilizable and metricas),
        "distancia_estimada_metros": metricas["distancia_estimada_metros"] if reutilizable and metricas else None,
        "duracion_estimada_segundos": metricas["duracion_estimada_segundos"] if reutilizable and metricas else None,
        **presentar_tramos(disponible if reutilizable else None, firma, paradas),
    }


def _reservar_consumo(ahora):
    # Orden fijo de bloqueo, compartido por todos los motoristas de esta base.
    fecha = timezone.localdate(ahora)
    contadores = []
    for periodo, inicio, limite in (
        ("DIARIO", fecha, settings.RUTAS_GOOGLE_LIMITE_DIARIO),
        ("MENSUAL", fecha.replace(day=1), settings.RUTAS_GOOGLE_LIMITE_MENSUAL),
    ):
        contador, _ = ConsumoRutasGoogle.objects.get_or_create(periodo=periodo, fecha=inicio)
        contador = ConsumoRutasGoogle.objects.select_for_update().get(pk=contador.pk)
        if contador.intentos_reservados >= limite:
            raise ErrorRutaVial("LIMITE_CONSUMO", "Se alcanzó el límite de cálculos de rutas configurado.", 429)
        contadores.append(contador)
    for contador in contadores:
        contador.intentos_reservados += 1
        contador.save(update_fields=("intentos_reservados", "actualizado_en"))


def _exigir_dia_operativo_vigente(repartidor, paradas, ahora):
    """No depende de que la tarea local ya haya cerrado el día anterior."""
    if settings.MODO_APLICACION != "CORPORATIVO":
        return
    from apps.jornadas.models import JornadaRepartidor
    from apps.solicitudes.models import Solicitud
    from apps.solicitudes.vigencia import limite_dia_operativo

    inicio_jornada = JornadaRepartidor.objects.filter(
        repartidor=repartidor, estado="ACTIVA",
    ).values_list("iniciada_en", flat=True).first()
    jornadas_vencidas = (
        inicio_jornada is not None and repartidor.empresa_id is not None
        and ahora >= limite_dia_operativo(inicio_jornada, repartidor.empresa)
    )
    solicitudes = Solicitud.objects.filter(
        pk__in={p["solicitud_id"] for p in paradas},
    ).select_related("empresa__pais")
    if jornadas_vencidas or any(
        ahora >= limite_dia_operativo(s.creado_en, s.empresa) for s in solicitudes
    ):
        raise ErrorRutaVial(
            "DIA_OPERATIVO_FINALIZADO",
            "El día operativo terminó; no se puede calcular ni reutilizar esta ruta.",
        )


def calcular_mi_ruta(usuario, version_actual, reintentar=False):
    propio = _obtener_repartidor_propio(usuario)
    if not usuario_tiene_permiso(usuario, "ruta.calcular", empresa=propio.empresa):
        raise PermissionDenied('No tiene el permiso requerido: "ruta.calcular".')
    ahora = timezone.now()
    # Publicar la nueva versión incluso si el cliente envió una versión antigua.
    # Así el siguiente GET puede conocerla; una validación no la revierte.
    with transaction.atomic():
        repartidor = Repartidor.objects.select_for_update().get(pk=propio.pk, activo=True)
        _exigir_dia_operativo_vigente(repartidor, obtener_paradas_operativas(repartidor), timezone.now())
        sincronizar_ruta(repartidor, VersionRuta.Motivo.CAMBIO_ESTADO)
    limpiar_geometria_vencida(ahora)
    with transaction.atomic():
        repartidor = Repartidor.objects.select_for_update().get(pk=propio.pk, activo=True)
        ahora = timezone.now()
        ruta = RutaRepartidor.objects.select_for_update().filter(
            repartidor=repartidor, estado=RutaRepartidor.Estado.ACTIVA,
        ).first()
        version = ruta.versiones.order_by("-numero").first() if ruta else None
        if not version or version.numero != version_actual:
            raise ErrorRutaVial("VERSION_DESACTUALIZADA", "Actualiza mi-ruta antes de calcular: cambió la versión del itinerario.")
        paradas = obtener_paradas_operativas(repartidor)
        _exigir_dia_operativo_vigente(repartidor, paradas, ahora)
        firma = firma_paradas(paradas)
        if not firma:
            raise ErrorRutaVial("SIN_PARADAS_CARTOGRAFIABLES", "No hay paradas con mapa para calcular; los envíos especiales solo registran kilómetros.")
        reutilizable = calculo_reutilizable(ruta, firma, ahora)
        actualizar_desglose = bool(reutilizable and not tiene_desglose(reutilizable) and reintentar)
        if reutilizable and not actualizar_desglose:
            return presentar_ruta_vial(ruta, paradas, version.numero, calculo=reutilizable)
        if not settings.HABILITAR_RUTAS_GOOGLE or not settings.CLAVE_API_GOOGLE_MAPS:
            raise ErrorRutaVial("GOOGLE_NO_CONFIGURADO", "El cálculo con Google todavía no está habilitado.", 503)
        previo = CalculoRutaVial.objects.select_for_update().filter(version=version).first()
        if CalculoRutaVial.objects.filter(
            version__ruta=ruta, estado="CALCULANDO",
            iniciada_en__gt=ahora - timedelta(seconds=max(60, settings.RUTAS_GOOGLE_TIMEOUT_SEGUNDOS * 3)),
        ).exists():
            raise ErrorRutaVial("CALCULO_EN_CURSO", "Ya existe un cálculo en curso; consulta mi-ruta, sin repetir el POST.")
        if previo:
            # Un proceso interrumpido requiere igualmente reintento explícito.
            if previo.estado == "CALCULADA" and not actualizar_desglose:
                raise ErrorRutaVial("RUTA_VENCIDA", "El trazado inicial venció; consulta las paradas en el mapa integrado. No se recalcula la misma versión.")
            if not reintentar:
                raise ErrorRutaVial("REINTENTO_EXPLICITO_REQUERIDO", "El intento anterior no terminó correctamente; no se reintenta automáticamente.")
            if previo.intentos >= settings.RUTAS_GOOGLE_INTENTOS_POR_VERSION:
                raise ErrorRutaVial("LIMITE_INTENTOS", "Se alcanzó el límite de intentos para esta versión.")
            if previo.estado == "FALLIDA" and previo.reintento_desde is None:
                raise ErrorRutaVial("FALLA_NO_REINTENTABLE", "Corrige la configuración o el itinerario antes de intentar otro cálculo.")
            if previo.reintento_desde and previo.reintento_desde > ahora:
                raise ErrorRutaVial("ESPERAR_REINTENTO", "Todavía no se permite reintentar este cálculo.", 429)
        punto = posiciones_vigentes(ahora).filter(repartidor=repartidor).first()
        if not punto:
            raise ErrorRutaVial("GPS_NO_VIGENTE", "Inicia la jornada y envía una posición GPS reciente y precisa antes de calcular.")
        origen = {"latitud": str(punto.latitud), "longitud": str(punto.longitud),
                  "registrada_en": punto.registrada_en.isoformat(), "precision_metros": str(punto.precision_metros)}
        _reservar_consumo(ahora)
        token = uuid4()
        calculo, _ = CalculoRutaVial.objects.update_or_create(version=version, defaults={
            "estado": "CALCULANDO", "intentos": previo.intentos + 1 if previo else 1,
            "token_intento": token, "iniciada_en": ahora, "calculada_en": None,
            "expira_en": None, "reintento_desde": None, "codigo_error": "",
            "origen_gps": origen, "paradas_calculadas": firma, "polilinea_codificada": "",
            "polilineas_tramos": [],
        })
        calculo_id = calculo.pk
    # No mantener bloqueado al motorista durante la llamada de red.
    destinos = destinos_unicos(firma)
    resultado, error = None, None
    try:
        resultado = calcular_ruta_google(origen, destinos)
    except ErrorProveedorGoogle as fallo:
        error = fallo
    with transaction.atomic():
        repartidor = Repartidor.objects.select_for_update().get(pk=propio.pk)
        calculo = CalculoRutaVial.objects.select_for_update().select_related("version").get(pk=calculo_id)
        if calculo.token_intento != token:
            raise ErrorRutaVial("INTENTO_REEMPLAZADO", "Este intento fue reemplazado; consulta el estado actual.")
        paradas = obtener_paradas_operativas(repartidor)
        vencimiento = None
        try:
            _exigir_dia_operativo_vigente(repartidor, paradas, timezone.now())
        except ErrorRutaVial as fallo:
            vencimiento = fallo
        ultima = ruta.versiones.order_by("-numero").first()
        cambio = ultima.pk != version.pk or firma_paradas(paradas) != firma
        calculo.estado = "FALLIDA" if error or cambio or vencimiento else "CALCULADA"
        calculo.codigo_error = vencimiento.detail["codigo"] if vencimiento else (
            "ITINERARIO_CAMBIO" if cambio else (error.codigo if error else "")
        )
        if error and error.reintentable and not cambio and not vencimiento:
            calculo.reintento_desde = timezone.now() + timedelta(seconds=30 * 2 ** (calculo.intentos - 1))
        if not error and not cambio and not vencimiento:
            calculo.calculada_en = timezone.now()
            calculo.expira_en = calculo.calculada_en + timedelta(hours=settings.RUTAS_GOOGLE_CACHE_HORAS)
            calculo.polilinea_codificada = resultado["polilinea_codificada"]
            calculo.polilineas_tramos = resultado.get("polilineas_tramos", [])
        calculo.save()
        salida = presentar_ruta_vial(ruta, paradas, ultima.numero, calculo=calculo, metricas=resultado)
    if vencimiento:
        raise vencimiento
    if cambio:
        raise ErrorRutaVial("ITINERARIO_CAMBIO", "El itinerario cambió durante el cálculo; actualiza mi-ruta.")
    if error:
        raise ErrorRutaVial(error.codigo, "No fue posible calcular la ruta vial. Consulta ruta_vial para conocer si se permite un reintento.", 503)
    return salida
