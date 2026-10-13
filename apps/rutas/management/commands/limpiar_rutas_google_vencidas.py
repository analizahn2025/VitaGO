from django.core.management.base import BaseCommand

from apps.rutas.ruta_vial import limpiar_geometria_vencida


class Command(BaseCommand):
    help = "Elimina únicamente geometrías de Google vencidas; conserva la auditoría y las paradas propias."

    def handle(self, *args, **options):
        cantidad = limpiar_geometria_vencida()
        self.stdout.write(f"Geometrías vencidas eliminadas: {cantidad}.")
