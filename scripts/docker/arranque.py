"""Espera acotada y preparación exclusivamente para órdenes de servidor."""

import os
from math import isfinite
from pathlib import Path
import subprocess
import sys
import time


def es_servidor(orden):
    if not orden:
        return False
    programa = Path(orden[0]).name
    if programa == "gunicorn":
        return True
    if programa.startswith("python"):
        return (orden[1:3] == ["-m", "gunicorn"] or
                len(orden) > 2 and Path(orden[1]).name == "manage.py" and orden[2] == "runserver")
    return False


def esperar_base_datos(segundos=60, intervalo=2):
    if not isfinite(segundos) or not isfinite(intervalo) or segundos <= 0 or intervalo <= 0:
        raise ValueError("Los tiempos de espera deben ser positivos.")
    limite = time.monotonic() + segundos
    while (restante := limite - time.monotonic()) > 0:
        try:
            resultado = subprocess.run(
                [sys.executable, "-m", "scripts.docker.base_datos", "comprobar"],
                timeout=min(5, restante), capture_output=True,
            )
            if resultado.returncode == 0:
                return
        except subprocess.TimeoutExpired:
            pass
        print("Esperando disponibilidad real de PostgreSQL...", flush=True)
        restante = limite - time.monotonic()
        if restante > 0:
            time.sleep(min(intervalo, restante))
    raise TimeoutError("PostgreSQL no estuvo disponible dentro del plazo configurado.")


def main(orden=None):
    orden = sys.argv[1:] if orden is None else orden
    es_prueba = (len(orden) > 2 and Path(orden[1]).name == "manage.py" and orden[2] == "test"
                 or orden[1:4] == ["-m", "django", "test"])
    if es_prueba and os.environ.get("DJANGO_SETTINGS_MODULE") not in {
        "config.settings.pruebas", "config.settings.pruebas_postgresql",
    }:
        print("Use el contenedor y la configuración aislada de pruebas.", file=sys.stderr)
        return 1
    if not es_servidor(orden):
        return 0
    try:
        esperar_base_datos(float(os.environ.get("SEGUNDOS_ESPERA_BASE_DATOS", "60")),
                          float(os.environ.get("INTERVALO_ESPERA_BASE_DATOS", "2")))
        return subprocess.run([sys.executable, "-m", "scripts.docker.base_datos", "preparar"]).returncode
    except (ValueError, TimeoutError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
