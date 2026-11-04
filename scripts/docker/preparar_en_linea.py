"""Valida Corporate externo y prepara solo la configuración general de Docker."""

import os
from pathlib import Path
from urllib.parse import unquote, urlsplit
from unittest.mock import patch

import environ


def leer_entorno(ruta):
    with patch.dict(os.environ, {}, clear=True):
        environ.Env.read_env(ruta, overwrite=True)
        return dict(os.environ)


def validar_corporativo(datos):
    if datos.get("MODO_APLICACION") != "CORPORATIVO":
        raise ValueError("El archivo debe corresponder a Corporate.")
    conexion = urlsplit(datos.get("URL_BASE_DATOS", ""))
    if (conexion.scheme not in {"postgres", "postgresql"}
            or unquote(conexion.path.lstrip("/")) != "vitago_corporativo"
            or datos.get("NOMBRE_BASE_DATOS", "vitago_corporativo") != "vitago_corporativo"):
        raise ValueError("La base debe ser exclusivamente vitago_corporativo.")
    if not conexion.hostname or conexion.hostname in {"localhost", "127.0.0.1", "::1", "bd_corporativa", "bd_network", "host.docker.internal"}:
        raise ValueError("Corporate requiere una conexión PostgreSQL en línea.")
    if datos.get("PROVEEDOR_AUTENTICACION") == "LOCAL":
        if datos.get("ENTORNO") != "PRUEBAS":
            raise ValueError("El proveedor local de Corporate requiere ENTORNO=PRUEBAS.")
        claves = [datos.get(k, "") for k in ("CLAVE_SECRETA", "CLAVE_FIRMA_JWT_LOCAL", "CLAVE_HASH_TOKEN_REFRESCO_LOCAL")]
        if any(len(c.encode("utf-8")) < 32 for c in claves) or len(set(claves)) != 3:
            raise ValueError("Las tres claves de Corporate deben ser seguras e independientes.")


def preparar(raiz):
    archivo_general = raiz / ".env.docker"
    datos = leer_entorno(archivo_general) if archivo_general.is_file() else {}
    corporativo = raiz / datos.get("ARCHIVO_ENV_CORPORATIVO", ".env.render.corporativo")
    if not corporativo.is_file():
        raise ValueError("Falta el archivo privado Corporate indicado por ARCHIVO_ENV_CORPORATIVO (.env.render.corporativo por defecto).")
    validar_corporativo(leer_entorno(corporativo))
    if not archivo_general.exists():
        from scripts.docker.crear_entorno_local import crear_entorno
        crear_entorno(raiz)
    return corporativo


if __name__ == "__main__":
    try:
        preparar(Path(__file__).resolve().parents[2])
        print("Entorno validado: Corporate en línea y Network local. No se duplican ni sobrescriben archivos privados.")
    except ValueError as error:
        print(str(error))
        raise SystemExit(1)
