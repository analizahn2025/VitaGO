"""Configuración de ejecución compartida por los despliegues de VitaGo."""

from dataclasses import dataclass
from enum import StrEnum

from django.core.exceptions import ImproperlyConfigured


class ModoAplicacion(StrEnum):
    """Modos de despliegue admitidos por VitaGo."""

    CORPORATIVO = "CORPORATIVO"
    EXTERNO = "EXTERNO"


def interpretar_modo_aplicacion(valor: str) -> ModoAplicacion:
    """Devuelve un modo de despliegue validado."""
    try:
        return ModoAplicacion(valor.strip().upper())
    except ValueError as exc:
        valores_validos = ", ".join(modo.value for modo in ModoAplicacion)
        raise ImproperlyConfigured(
            f"MODO_APLICACION debe ser uno de estos valores: {valores_validos}."
        ) from exc


@dataclass(frozen=True, slots=True)
class Funcionalidades:
    """Configuración central; nunca sustituye la autorización."""

    tarifas: bool
    repartidores_compartidos: bool
    mantenimiento_flota: bool

