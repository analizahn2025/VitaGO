"""Tarea local idempotente de recuperación de la operación corporativa."""

import json
import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.solicitudes.contingencias import procesar_cierre_diario


class Command(BaseCommand):
    help = "Cierra servicios/jornadas corporativos vencidos y recupera reasignaciones por suspensión."

    def add_arguments(self, parser):
        parser.add_argument("--confirmar-corporativo", action="store_true",
                            help="Confirma que este comando puede cerrar operaciones Corporate.")

    def handle(self, *args, **opciones):
        if settings.MODO_APLICACION != "CORPORATIVO":
            raise CommandError("Esta tarea solo puede ejecutarse en Corporate; Network no se modifica.")
        if not opciones["confirmar_corporativo"]:
            raise CommandError("Debe indicar --confirmar-corporativo para modificar operaciones vencidas.")
        resultado = procesar_cierre_diario()
        logging.getLogger("vitago.api").info("Mantenimiento Corporate: %s", json.dumps(resultado, ensure_ascii=False))
        # pythonw.exe no dispone de stdout; el resultado ya queda en el log.
        if self.stdout._out is not None:
            self.stdout.write(json.dumps(resultado, ensure_ascii=False))
        if resultado.get("errores"):
            raise CommandError("Quedaron operaciones pendientes. Revise el registro; se reintentarán en la siguiente ejecución.")
