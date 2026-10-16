"""Indicaciones de presentación del mapa propio; nunca genera enlaces externos."""


def presentar_mapa_integrado(paradas, ruta_vial):
    proxima = paradas[0] if paradas else None
    mostrar_mapa = bool(
        proxima
        and proxima["presentacion_ruta"] == "MAPA"
        and proxima.get("ubicacion")
    )
    return {
        "modo": "INTEGRADO",
        "proveedor": "GOOGLE_MAPS",
        "mostrar_mapa": mostrar_mapa,
        "mostrar_trazado": mostrar_mapa and ruta_vial["estado"] == "CALCULADA",
        "permite_navegacion_externa": False,
    }
