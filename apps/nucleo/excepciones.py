"""Formato estable para errores de validación anidados."""

from rest_framework.views import exception_handler


def _errores_articulos(errores):
    detalles = []
    if not isinstance(errores, list):
        return errores
    for indice, campos in enumerate(errores):
        if not isinstance(campos, dict):
            if campos:
                detalles.append(
                    {"indice": indice, "campo": "articulos", "mensaje": campos}
                )
            continue
        for campo, mensajes in campos.items():
            if isinstance(mensajes, list):
                for mensaje in mensajes:
                    detalles.append(
                        {"indice": indice, "campo": campo, "mensaje": mensaje}
                    )
            else:
                detalles.append(
                    {"indice": indice, "campo": campo, "mensaje": mensajes}
                )
    return detalles


def manejador_excepciones(error, contexto):
    respuesta = exception_handler(error, contexto)
    if (
        respuesta is not None
        and respuesta.status_code == 400
        and isinstance(respuesta.data, dict)
        and isinstance(respuesta.data.get("articulos"), list)
        and not all(
            isinstance(item, dict) and "indice" in item
            for item in respuesta.data["articulos"]
        )
    ):
        respuesta.data["articulos"] = _errores_articulos(
            respuesta.data["articulos"]
        )
    return respuesta
