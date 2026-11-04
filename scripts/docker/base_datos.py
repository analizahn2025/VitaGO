"""Preparación antes de WSGI; migraciones serializadas por base PostgreSQL."""

import os
from math import isfinite
import sys
import time


def bandera(nombre, predeterminado=True):
    valor = os.environ.get(nombre, str(predeterminado)).strip().lower()
    if valor not in {"true", "false", "1", "0"}:
        raise ValueError(f"{nombre} debe ser true o false.")
    return valor in {"true", "1"}


def preparar(connection, ejecutar):
    if bandera("APLICAR_MIGRACIONES"):
        segundos = float(os.environ.get("SEGUNDOS_ESPERA_MIGRACIONES", "120"))
        if not isfinite(segundos) or segundos <= 0:
            raise ValueError("SEGUNDOS_ESPERA_MIGRACIONES debe ser positivo.")
        limite = time.monotonic() + segundos
        adquirido = False
        try:
            while time.monotonic() < limite:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_try_advisory_lock(%s)", [1464420167])
                    adquirido = cursor.fetchone()[0]
                if adquirido:
                    break
                time.sleep(min(1, max(0, limite - time.monotonic())))
            if not adquirido:
                raise TimeoutError("Otro contenedor mantiene el bloqueo de migraciones.")
            print("Aplicando migraciones idempotentes...", flush=True)
            ejecutar("migrate", interactive=False, verbosity=1)
        finally:
            if adquirido:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", [1464420167])
    if bandera("PREPARAR_ESTATICOS"):
        print("Preparando archivos estáticos...", flush=True)
        ejecutar("collectstatic", interactive=False, verbosity=0)


def main():
    try:
        import django
        django.setup()
        from django.core.management import call_command
        from django.db import connection
        if connection.vendor != "postgresql":
            raise ValueError("El contenedor de servidor requiere PostgreSQL.")
        if sys.argv[1:] == ["comprobar"]:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                assert cursor.fetchone()[0] == 1
        elif sys.argv[1:] == ["preparar"]:
            preparar(connection, call_command)
        else:
            raise ValueError("Operación de arranque desconocida.")
        connection.close()
        return 0
    except Exception as error:
        # No imprimir URLs, contraseñas ni los parámetros de la conexión.
        print(f"No se pudo preparar el backend ({type(error).__name__}). Revise la configuración del contenedor.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
