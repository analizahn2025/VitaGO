import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.evidencias.mantenimiento import mantener_imagenes


class Command(BaseCommand):
    help = "Importa fotografías a Base64 en la BD y elimina imágenes anteriores al mes pasado."

    def add_arguments(self, parser):
        parser.add_argument("--modo-esperado", choices=("CORPORATIVO", "EXTERNO"), required=True)
        parser.add_argument("--conservar-originales", action="store_true", help="Copia sin retirar originales, para verificar varios destinos antes de limpiar.")
        accion = parser.add_mutually_exclusive_group(required=True)
        accion.add_argument("--simular", action="store_true")
        accion.add_argument("--confirmar", action="store_true")

    def handle(self, *args, **opciones):
        if bool(opciones["confirmar"]) == bool(opciones["simular"]):
            raise CommandError("Indique exactamente una acción: --confirmar o --simular.")
        if settings.MODO_APLICACION != opciones["modo_esperado"]:
            raise CommandError("El modo del entorno no coincide con --modo-esperado.")
        resultado = mantener_imagenes(simular=opciones["simular"], retirar_originales=not opciones["conservar_originales"])
        self.stdout.write(json.dumps(resultado, ensure_ascii=False))
        if resultado["pendiente"]:
            raise CommandError("Quedan originales o imágenes pendientes; revise los conteos, sin compartir fotografías.")
