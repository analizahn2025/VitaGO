import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.rutas.ruta_vial import limpiar_geometria_vencida


class Command(BaseCommand):
    help = "Elimina únicamente geometrías de Google vencidas; conserva la auditoría y las paradas propias."

    def add_arguments(self, parser):
        parser.add_argument("--confirmar-corporativo", action="store_true",
                            help="Exige modo Corporate para la tarea programada local.")

    def handle(self, *args, **options):
        if options["confirmar_corporativo"] and settings.MODO_APLICACION != "CORPORATIVO":
            raise CommandError("La tarea Corporate no puede ejecutar limpieza en Network.")
        registro = logging.getLogger("vitago.api")
        try:
            cantidad = limpiar_geometria_vencida()
        except Exception:
            registro.exception("Falló la limpieza de geometrías Google vencidas.")
            raise
        mensaje = f"Geometrías vencidas eliminadas: {cantidad}."
        registro.info("Limpieza Google: %s", mensaje)
        # pythonw.exe no tiene stdout; conservar el resultado en el log.
        if self.stdout._out is not None:
            self.stdout.write(mensaje)
