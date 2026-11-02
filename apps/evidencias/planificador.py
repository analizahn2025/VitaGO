"""Temporizador del servidor: mantenimiento aun cuando no llegan peticiones."""

import logging
import os
import sys
import threading

from django.conf import settings
from django.db import connections


registro = logging.getLogger("vitago.api")
_candado = threading.Lock()
_hilo = None
_proceso = None


def _ejecutar(detener):
    from apps.evidencias.mantenimiento import recuperar_imagenes
    while not detener.wait(60):
        try:
            recuperar_imagenes()
        except Exception:
            registro.warning("El mantenimiento de imágenes se reintentará en la próxima revisión.")
        finally:
            # La conexión del hilo nunca pertenece a una petición HTTP.
            connections.close_all()


def iniciar_planificador_imagenes():
    global _hilo, _proceso
    if not settings.HABILITAR_MANTENIMIENTO_IMAGENES:
        return
    with _candado:
        proceso = os.getpid()
        if _proceso == proceso and _hilo is not None and _hilo.is_alive():
            return
        _proceso = proceso
        _hilo = threading.Thread(target=_ejecutar, args=(threading.Event(),),
                                 name="vitago-retencion-imagenes", daemon=True)
        _hilo.start()


def iniciar_planificador_servidor():
    # Gunicorn usa post_worker_init; no crear un hilo dentro del master con --preload.
    if "gunicorn" not in sys.modules:
        iniciar_planificador_imagenes()


def _reiniciar_tras_fork():
    global _candado, _hilo, _proceso
    _candado = threading.Lock()
    _hilo = None
    _proceso = None
    # Un candado del padre no debe heredarse tomado por su hilo de mantenimiento.
    from apps.evidencias.mantenimiento import _recuperador
    _recuperador._candado = threading.Lock()
    _recuperador._revisada_en = None
    _recuperador._siguiente = None


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reiniciar_tras_fork)
