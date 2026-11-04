"""Cobertura administrativa corporativa; no representa distancia ni una ruta vial."""

from apps.geografia.normalizacion import clave_departamento


def departamento_normalizado(ubicacion):
    return clave_departamento(ubicacion.nivel_administrativo_1)


def comparten_departamento(origen, destino):
    departamento = departamento_normalizado(origen)
    return bool(
        origen.pais_id == destino.pais_id
        and departamento
        and departamento == departamento_normalizado(destino)
    )
