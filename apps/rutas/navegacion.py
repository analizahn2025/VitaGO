"""Enlaces de navegación externos construidos únicamente con ubicaciones propias."""

from urllib.parse import urlencode


def navegacion_parada(parada):
    if not parada or parada["presentacion_ruta"] != "MAPA" or not parada.get("ubicacion"):
        return None
    ubicacion = parada["ubicacion"]
    destino = f"{ubicacion.latitud},{ubicacion.longitud}"
    return {
        "proveedor": "GOOGLE_MAPS", "requiere_clave_api": False,
        "solicitud_id": str(parada["solicitud_id"]), "tipo_parada": parada["tipo"],
        "url": "https://www.google.com/maps/dir/?" + urlencode({
            "api": 1, "destination": destino,
            "travelmode": "two-wheeler", "dir_action": "navigate",
        }),
    }
