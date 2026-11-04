"""Un único arranque Docker desde cualquier carpeta de PowerShell."""

import argparse
from pathlib import Path
import subprocess
import sys


def orden_compose(raiz):
    return ["docker", "compose", "--project-directory", str(raiz), "--project-name", "vitago",
            "--env-file", str(raiz / ".env.docker"), "-f", str(raiz / "docker-compose.yml")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sin-construir", action="store_true", help="Usar una imagen ya construida o publicada.")
    opciones = parser.parse_args()
    raiz = Path(__file__).resolve().parents[2]
    python = next((str(p) for p in (raiz / ".venv/Scripts/python.exe", raiz / ".venv/bin/python") if p.is_file()), sys.executable)
    subprocess.run([python, "-m", "scripts.docker.preparar_en_linea"], cwd=raiz, check=True)
    orden = orden_compose(raiz)
    subprocess.run(orden + ["config", "--quiet"], cwd=raiz, check=True)
    argumentos = ["up", "-d", "--wait", "--wait-timeout", "180"]
    argumentos.append("--no-build" if opciones.sin_construir else "--build")
    subprocess.run(orden + argumentos, cwd=raiz, check=True)
    subprocess.run(orden + ["ps"], cwd=raiz, check=True)


if __name__ == "__main__":
    main()
