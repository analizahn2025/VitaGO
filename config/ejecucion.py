"""Configuración de ejecución compartida por los despliegues de VitaGo."""

from dataclasses import dataclass
from enum import StrEnum

from django.core.exceptions import ImproperlyConfigured


class ModoAplicacion(StrEnum):
    """Modos de despliegue admitidos por VitaGo."""

    CORPORATIVO = "CORPORATIVO"
    EXTERNO = "EXTERNO"


class ProveedorAutenticacion(StrEnum):
    """Proveedores de identidad admitidos por VitaGo."""

    LOCAL = "LOCAL"
    JWT_CORPORATIVO = "JWT_CORPORATIVO"


def interpretar_modo_aplicacion(valor: str) -> ModoAplicacion:
    """Devuelve un modo de despliegue validado."""
    try:
        return ModoAplicacion(valor.strip().upper())
    except ValueError as exc:
        valores_validos = ", ".join(modo.value for modo in ModoAplicacion)
        raise ImproperlyConfigured(
            f"MODO_APLICACION debe ser uno de estos valores: {valores_validos}."
        ) from exc


def interpretar_proveedor_autenticacion(valor: str) -> ProveedorAutenticacion:
    """Devuelve un proveedor de autenticación validado."""
    try:
        return ProveedorAutenticacion(valor.strip().upper())
    except ValueError as exc:
        valores_validos = ", ".join(
            proveedor.value for proveedor in ProveedorAutenticacion
        )
        raise ImproperlyConfigured(
            "PROVEEDOR_AUTENTICACION debe ser uno de estos valores: "
            f"{valores_validos}."
        ) from exc


@dataclass(frozen=True, slots=True)
class Funcionalidades:
    """Configuración central; nunca sustituye la autorización."""

    tarifas: bool
    repartidores_compartidos: bool
    mantenimiento_flota: bool
