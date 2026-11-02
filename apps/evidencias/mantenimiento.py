"""Importación verificable y retención mensual, sin borrar registros de evidencia."""

import base64
import logging
import threading
import time
from datetime import timedelta

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connections, transaction
from django.db.models import Q
from django.utils import timezone

from apps.evidencias.imagenes import corte_retencion, inicio_mes, preparar_imagen_base64


registro = logging.getLogger("vitago.api")


def _modelos():
    from apps.evidencias.models import EvidenciaSolicitud
    from apps.incidencias.models import EvidenciaIncidencia
    return (EvidenciaSolicitud, EvidenciaIncidencia)


def _eliminar_original(modelo, identificador, clave, resultado, contenido_esperado=None):
    """Después del commit; comprobar copia persistida antes de retirar el original."""
    try:
        evidencia = modelo.objects.get(pk=identificador)
        if evidencia.archivo_original_eliminado_en is not None:
            return
        if evidencia.imagen_eliminada_en is None:
            if contenido_esperado is None or evidencia.contenido_base64 != contenido_esperado:
                raise ValueError("No se verificó la copia persistida.")
        if clave and not clave.startswith("bd/"):
            default_storage.delete(clave)
        modelo.objects.filter(pk=identificador, archivo_original_eliminado_en__isnull=True).update(
            archivo_original_eliminado_en=timezone.now(),
        )
        resultado["originales_retirados"] += 1
    except Exception:
        resultado["errores"] += 1
        resultado["pendiente"] = True
        # No registrar nombres de archivos, fotos ni contenido Base64.
        registro.warning("Pendiente retirar un original de imagen ya copiada o vencida.")


def mantener_imagenes(*, ahora=None, simular=False, limite_segundos=None, retirar_originales=True):
    ahora = ahora or timezone.now()
    corte = corte_retencion(ahora)
    inicio = time.monotonic()
    resultado = {
        "simulacion": simular, "corte_exclusivo": corte.isoformat(),
        "zona_horaria_operativa": str(timezone.get_default_timezone()),
        "imagenes_vencidas": 0, "imagenes_migradas": 0,
        "originales_retirados": 0, "originales_no_disponibles": 0,
        "errores": 0, "pendiente": False,
    }

    def agotado():
        if limite_segundos is not None and time.monotonic() - inicio >= limite_segundos:
            resultado["pendiente"] = True
            return True
        return False

    for modelo in _modelos():
        vencidas = modelo.objects.filter(capturada_en__lt=corte).filter(
            Q(imagen_eliminada_en__isnull=True) | Q(archivo_original_eliminado_en__isnull=True),
        ).order_by("capturada_en", "id")
        if simular:
            resultado["imagenes_vencidas"] += vencidas.filter(imagen_eliminada_en__isnull=True).count()
        else:
            # Vaciar texto por lotes sin traer fotografías a Python ni una consulta por foto.
            por_purgar = modelo.objects.filter(capturada_en__lt=corte, imagen_eliminada_en__isnull=True)
            while True:
                if agotado():
                    return resultado
                ids = list(por_purgar.order_by("capturada_en", "id").values_list("pk", flat=True)[:500])
                if not ids:
                    break
                resultado["imagenes_vencidas"] += por_purgar.filter(pk__in=ids).update(
                    contenido_base64=None, imagen_eliminada_en=ahora,
                )
            originales_vencidos = vencidas.filter(archivo_original_eliminado_en__isnull=True) if retirar_originales else vencidas.none()
            for identificador in originales_vencidos.values_list("pk", flat=True).iterator(chunk_size=100):
                if agotado():
                    return resultado
                try:
                    with transaction.atomic():
                        evidencia = modelo.objects.select_for_update().get(pk=identificador)
                        if evidencia.capturada_en >= corte:
                            continue
                        if retirar_originales and evidencia.archivo_original_eliminado_en is None:
                            transaction.on_commit(lambda m=modelo, i=identificador, c=evidencia.clave_almacenamiento:
                                                  _eliminar_original(m, i, c, resultado))
                except Exception:
                    resultado["errores"] += 1
                    registro.warning("Pendiente aplicar retención a una imagen.")

        # Una fila importada con retirada fallida debe reintentar sin releer el original.
        pendientes = modelo.objects.filter(
            capturada_en__gte=corte, imagen_eliminada_en__isnull=True,
        ).filter(Q(imagen_guardada_en__isnull=True) | Q(archivo_original_eliminado_en__isnull=True)).order_by("capturada_en", "id")
        if simular:
            resultado["imagenes_migradas"] += pendientes.filter(imagen_guardada_en__isnull=True).count()
            continue
        for identificador in pendientes.values_list("pk", flat=True).iterator(chunk_size=100):
            if agotado():
                return resultado
            try:
                with transaction.atomic():
                    evidencia = modelo.objects.select_for_update().get(pk=identificador)
                    if evidencia.imagen_eliminada_en is not None or evidencia.capturada_en < corte:
                        continue
                    if evidencia.imagen_guardada_en is None:
                        from apps.evidencias.servicios import validar_archivo_imagen
                        maximo = settings.TAMANO_MAXIMO_EVIDENCIA_MB * 1024 * 1024
                        try:
                            with default_storage.open(evidencia.clave_almacenamiento, "rb") as original:
                                contenido = original.read(maximo + 1)
                        except FileNotFoundError:
                            resultado["originales_no_disponibles"] += 1
                            continue
                        if len(contenido) != evidencia.tamano_bytes or len(contenido) > maximo:
                            raise ValueError("El original no coincide con los metadatos.")
                        archivo = SimpleUploadedFile("imagen", contenido, content_type=evidencia.tipo_contenido)
                        validar_archivo_imagen(archivo)
                        datos = preparar_imagen_base64(archivo, ahora)
                        # El original antiguo todavía existe hasta después del commit.
                        datos.pop("archivo_original_eliminado_en")
                        modelo.objects.filter(pk=identificador, imagen_eliminada_en__isnull=True).update(**datos)
                        codificado = datos["contenido_base64"]
                        assert base64.b64decode(codificado, validate=True) == contenido
                        resultado["imagenes_migradas"] += 1
                    else:
                        codificado = evidencia.contenido_base64
                    if retirar_originales and evidencia.archivo_original_eliminado_en is None:
                        transaction.on_commit(lambda m=modelo, i=identificador, c=evidencia.clave_almacenamiento, b=codificado:
                                              _eliminar_original(m, i, c, resultado, b))
            except Exception:
                resultado["errores"] += 1
                registro.warning("Pendiente importar una imagen anterior; se conserva su original.")
    resultado["pendiente"] = bool(resultado["errores"] or resultado["originales_no_disponibles"])
    return resultado


class RecuperadorImagenes:
    """Revisión acotada al arrancar/recibir tráfico, con recuperación de meses atrasados."""

    def __init__(self):
        self._candado = threading.Lock()
        self._revisada_en = None
        self._siguiente = None

    def recuperar(self, *, forzar=False):
        if not settings.HABILITAR_MANTENIMIENTO_IMAGENES:
            return
        ahora = timezone.now()
        if not forzar and self._revisada_en and self._revisada_en <= ahora < self._siguiente:
            return
        if not self._candado.acquire(blocking=False):
            return
        try:
            ahora = timezone.now()
            if not forzar and self._revisada_en and self._revisada_en <= ahora < self._siguiente:
                return
            correcta = False
            try:
                resultado = mantener_imagenes(ahora=ahora, limite_segundos=3)
                correcta = not resultado["pendiente"]
                if resultado["imagenes_vencidas"] or resultado["imagenes_migradas"] or not correcta:
                    registro.info("Mantenimiento de imágenes: %s", resultado)
            except Exception:
                registro.warning("Mantenimiento de imágenes pendiente; se reintentará automáticamente.")
            self._revisada_en = ahora
            self._siguiente = min(
                timezone.now() + timedelta(hours=1) if correcta else timezone.now() + timedelta(minutes=5),
                inicio_mes(ahora, 1),
            )
        finally:
            self._candado.release()


_recuperador = RecuperadorImagenes()


def recuperar_imagenes(*, forzar=False):
    _recuperador.recuperar(forzar=forzar)


def recuperar_imagenes_al_arrancar():
    if not settings.HABILITAR_MANTENIMIENTO_IMAGENES:
        return
    try:
        recuperar_imagenes(forzar=True)
    finally:
        for conexion in connections.all():
            if not conexion.in_atomic_block:
                conexion.close()
