"""Asocia geometría temporal con paradas propias; seleccionar no cambia la ruta."""


def _coordenadas(parada):
    return {"latitud": parada["latitud"], "longitud": parada["longitud"]}


def destinos_unicos(firma):
    destinos = []
    for parada in firma:
        coordenadas = _coordenadas(parada)
        if not destinos or destinos[-1] != coordenadas:
            destinos.append(coordenadas)
    return destinos


def tiene_desglose(calculo):
    polilineas = calculo.polilineas_tramos
    valido = (
        isinstance(polilineas, list) and bool(polilineas)
        and len(polilineas) == len(destinos_unicos(calculo.paradas_calculadas))
        and all(isinstance(linea, str) and len(linea) <= 200000
                and all(63 <= ord(c) <= 126 for c in linea) for linea in polilineas)
    )
    if not valido:
        return False
    anterior = _coordenadas(calculo.origen_gps)
    for linea, destino in zip(polilineas, destinos_unicos(calculo.paradas_calculadas)):
        if not linea and anterior != destino:
            return False
        anterior = destino
    return True


def presentar_tramos(calculo, firma, paradas):
    salida = {
        "modo_visualizacion": "UN_TRAMO",
        "desglose_disponible": False,
        "requiere_actualizar_desglose": False,
        "tramo_actual_id": None,
        "tramos": [],
    }
    if calculo is None:
        return salida
    if not tiene_desglose(calculo):
        salida["requiere_actualizar_desglose"] = True
        return salida

    originales = calculo.paradas_calculadas
    desplazamiento = len(originales) - len(firma)
    orden_envios = {identificador: numero for numero, identificador in enumerate(
        dict.fromkeys(p["solicitud_id"] for p in originales), start=1,
    )}
    pendientes = {(str(p["solicitud_id"]), p["tipo"]): p for p in paradas}
    indice_geometria = -1
    for indice, parada in enumerate(originales):
        mismo_punto = indice > 0 and _coordenadas(parada) == _coordenadas(originales[indice - 1])
        if not mismo_punto:
            indice_geometria += 1
        if indice < desplazamiento:
            continue
        operativa = pendientes[(parada["solicitud_id"], parada["tipo"])]
        anterior = originales[indice - 1] if indice else calculo.origen_gps
        linea = None if mismo_punto else calculo.polilineas_tramos[indice_geometria]
        salida["tramos"].append({
            "tramo_id": f'{parada["solicitud_id"]}:{parada["tipo"]}',
            "solicitud_id": parada["solicitud_id"],
            "numero_solicitud": operativa["numero_solicitud"],
            "orden_envio": orden_envios[parada["solicitud_id"]],
            "orden_parada": operativa["orden"],
            "tipo_parada": parada["tipo"],
            "estado_solicitud": operativa["estado_solicitud"],
            "es_proximo": operativa["orden"] == 1,
            "origen": {
                "tipo": "PARADA" if indice else "GPS",
                "ubicacion_id": anterior.get("ubicacion_id"), **_coordenadas(anterior),
            },
            "destino": {"ubicacion_id": parada["ubicacion_id"], **_coordenadas(parada)},
            "polilinea_codificada": linea or None,
            "sin_desplazamiento": mismo_punto or not linea,
        })
    salida["desglose_disponible"] = True
    if salida["tramos"] and salida["tramos"][0]["es_proximo"]:
        salida["tramo_actual_id"] = salida["tramos"][0]["tramo_id"]
    return salida
