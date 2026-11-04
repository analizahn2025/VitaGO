"""Comprueba HTTP y disponibilidad SQL mediante el endpoint público mínimo."""

import json
import os
from urllib.request import urlopen


def main():
    try:
        puerto = int(os.environ.get("PORT", "8000"))
        with urlopen(f"http://127.0.0.1:{puerto}/api/v1/salud/disponibilidad/", timeout=4) as respuesta:
            return 0 if respuesta.status == 200 and json.loads(respuesta.read(4096)).get("estado") == "correcto" else 1
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
