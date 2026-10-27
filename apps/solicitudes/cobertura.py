"""Cobertura administrativa corporativa; no representa distancia ni una ruta vial."""

from unicodedata import normalize


def departamento_normalizado(ubicacion):
    texto = normalize("NFC", ubicacion.nivel_administrativo_1 or "")
    return " ".join(texto.split()).casefold()


def comparten_departamento(origen, destino):
    departamento = departamento_normalizado(origen)
    return bool(
        origen.pais_id == destino.pais_id
        and departamento
        and departamento == departamento_normalizado(destino)
    )
