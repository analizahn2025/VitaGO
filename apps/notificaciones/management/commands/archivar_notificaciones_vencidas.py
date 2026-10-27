"""Mantenimiento exclusivo de avisos, sin cerrar operaciones ni consultar GPS."""

import json
import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.notificaciones.servicios import archivar_notificaciones_vencidas


class Command(BaseCommand):
    help = "Archiva avisos anteriores al día operativo del servidor; conserva su historial."

    def add_arguments(self, parser):
        parser.add_argument("--modo-esperado", choices=("CORPORATIVO", "EXTERNO"), required=True)
        accion = parser.add_mutually_exclusive_group(required=True)
        accion.add_argument("--confirmar", action="store_true")
        accion.add_argument("--simular", action="store_true")

    def handle(self, *args, **opciones):
        if bool(opciones["confirmar"]) == bool(opciones["simular"]):
            raise CommandError("Indique exactamente una acción: --confirmar o --simular.")
        if settings.MODO_APLICACION != opciones["modo_esperado"]:
            raise CommandError("El modo del entorno no coincide con --modo-esperado; no se archivó nada.")
        registro = logging.getLogger("vitago.api")
        try:
            resultado = archivar_notificaciones_vencidas(simular=opciones["simular"])
        except Exception:
            registro.exception("Falló el archivado de avisos; se recuperará en la próxima ejecución.")
            raise
        mensaje = json.dumps(resultado, ensure_ascii=False)
        registro.info("Archivado diario de avisos %s: %s", settings.MODO_APLICACION, mensaje)
        if self.stdout._out is not None:
            self.stdout.write(mensaje)
