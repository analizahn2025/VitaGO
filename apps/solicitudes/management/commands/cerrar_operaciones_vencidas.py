"""Mantenimiento idempotente del día operativo en Corporate y Network."""

import json
import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.solicitudes.contingencias import procesar_cierre_diario


class Command(BaseCommand):
    help = "Cierra servicios y jornadas a las 22:00 y recupera cierres atrasados."

    def add_arguments(self, parser):
        parser.add_argument("--confirmar-corporativo", action="store_true",
                            help="Confirma que este comando puede cerrar operaciones Corporate.")
        parser.add_argument("--confirmar-network", action="store_true",
                            help="Confirma que este comando puede cerrar operaciones Network.")

    def handle(self, *args, **opciones):
        corporativo = settings.MODO_APLICACION == "CORPORATIVO"
        bandera = "confirmar_corporativo" if corporativo else "confirmar_network"
        otra = "confirmar_network" if corporativo else "confirmar_corporativo"
        if not opciones[bandera] or opciones[otra]:
            raise CommandError(f"Debe indicar únicamente --{bandera.replace('_', '-')} para este despliegue.")
        resultado = procesar_cierre_diario()
        logging.getLogger("vitago.api").info("Mantenimiento %s: %s", settings.MODO_APLICACION, json.dumps(resultado, ensure_ascii=False))
        # pythonw.exe no dispone de stdout; el resultado ya queda en el log.
        if self.stdout._out is not None:
            self.stdout.write(json.dumps(resultado, ensure_ascii=False))
        if resultado.get("errores"):
            raise CommandError("Quedaron operaciones pendientes. Revise el registro; se reintentarán en la siguiente ejecución.")
