"""Recuperación al arrancar o reanudar el servidor, con reloj del backend."""

from datetime import timedelta
import logging
import threading

from django.conf import settings
from django.db import connections
from django.db.models import Min, Q
from django.utils import timezone

from apps.jornadas.horario import corte_jornada, periodo_operativo
from apps.jornadas.models import JornadaRepartidor
from apps.organizaciones.models import Empresa
from apps.solicitudes.contingencias import procesar_cierre_diario


registro = logging.getLogger("vitago.api")
INTERVALO_REVISION = timedelta(minutes=1)
INTERVALO_REINTENTO = timedelta(seconds=5)


def _limite_revision(ahora):
    limite = ahora + INTERVALO_REVISION
    corte_guardado = JornadaRepartidor.objects.filter(
        estado="ACTIVA", cierre_programado_en__gt=ahora,
    ).aggregate(corte=Min("cierre_programado_en"))["corte"]
    if corte_guardado is not None:
        limite = min(limite, corte_guardado)
    empresas = (
        Empresa.objects.select_related("pais").all()
        if settings.MODO_APLICACION == "CORPORATIVO" else [None]
    )
    for empresa in empresas:
        corte = periodo_operativo(ahora, empresa)[2]
        if ahora < corte < limite:
            limite = corte
    return limite


def _hay_jornadas_vencidas(ahora):
    candidatas = JornadaRepartidor.objects.filter(estado="ACTIVA").filter(
        Q(cierre_programado_en__lte=ahora) | Q(cierre_programado_en__isnull=True),
    ).select_related("repartidor__empresa__pais")
    return any(corte_jornada(jornada) <= ahora for jornada in candidatas.iterator(chunk_size=100))


class RecuperadorCierreOperativo:
    """Una revisión por proceso; los servicios serializan las filas entre workers."""

    def __init__(self):
        self._candado = threading.Lock()
        self._revision = None

    def _respuesta_vigente(self, ahora):
        revision = self._revision
        if revision is not None:
            modo, revisada_en, valida_hasta, correcta = revision
            if modo == settings.MODO_APLICACION and revisada_en <= ahora < valida_hasta:
                return correcta
        return None

    def recuperar(self, *, forzar=False):
        if not settings.HABILITAR_RECUPERACION_CIERRE:
            return True
        ahora = timezone.now()
        vigente = self._respuesta_vigente(ahora)
        if not forzar and vigente is not None:
            return vigente
        if not self._candado.acquire(timeout=5):
            return False
        try:
            ahora = timezone.now()
            vigente = self._respuesta_vigente(ahora)
            if not forzar and vigente is not None:
                return vigente
            self._revision = None
            correcta = False
            limite = ahora + INTERVALO_REINTENTO
            try:
                resultado = procesar_cierre_diario(
                    ahora, recuperar_suspensiones=False, limite_segundos=5,
                )
                if resultado.get("errores") or resultado.get("pendiente") or _hay_jornadas_vencidas(ahora):
                    registro.warning("Recuperación del cierre operativo pendiente; se reintentará.")
                    return False
                limite = _limite_revision(ahora)
                if timezone.now() >= limite:
                    # Una ejecución que cruza el corte no habilita solicitudes
                    # con una comprobación realizada antes de las 22:00.
                    return False
                correcta = True
                if resultado["solicitudes_cerradas"] or resultado["jornadas_cerradas"]:
                    registro.info("Cierres operativos recuperados: %s", resultado)
                return True
            except Exception:
                registro.exception("No se pudo recuperar el cierre operativo; se reintentará.")
                return False
            finally:
                if not correcta:
                    limite = timezone.now() + INTERVALO_REINTENTO
                # Publicar el resultado completo, nunca un estado intermedio
                # mientras otro hilo espera esta revisión.
                self._revision = (settings.MODO_APLICACION, ahora, limite, correcta)
        finally:
            self._candado.release()


_recuperador = RecuperadorCierreOperativo()


def recuperar_cierres_operativos(*, forzar=False):
    return _recuperador.recuperar(forzar=forzar)


def recuperar_al_arrancar():
    """Solo en las entradas del servidor; no se ejecuta al migrar ni en ready()."""
    if not settings.HABILITAR_RECUPERACION_CIERRE:
        return
    try:
        recuperar_cierres_operativos(forzar=True)
    finally:
        # Evita heredar conexiones abiertas si Gunicorn precarga antes del fork.
        for conexion in connections.all():
            if not conexion.in_atomic_block:
                conexion.close()
