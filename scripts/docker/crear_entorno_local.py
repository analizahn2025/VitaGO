"""Crea la configuración Docker y cuatro secretos exclusivos de Network."""

from pathlib import Path
import secrets
import sys


def crear_entorno(raiz):
    destino = raiz / ".env.docker"
    plantilla = (raiz / ".env.docker.example").read_text(encoding="utf-8")
    lineas = []
    for linea in plantilla.splitlines():
        clave, separador, valor = linea.partition("=")
        if separador and valor == "GENERAR" and clave.startswith("CLAVE_"):
            linea = f"{clave}={secrets.token_urlsafe(48)}"
        lineas.append(linea)
    # x impide reemplazar claves que ya protegen volúmenes y sesiones existentes.
    with destino.open("x", encoding="utf-8", newline="\n") as archivo:
        archivo.write("\n".join(lineas) + "\n")
    return destino


if __name__ == "__main__":
    try:
        crear_entorno(Path(__file__).resolve().parents[2])
        print("Creado .env.docker con secretos independientes. No se muestran sus valores.")
    except FileExistsError:
        print(".env.docker ya existe; se conserva sin cambios.", file=sys.stderr)
        raise SystemExit(1)
