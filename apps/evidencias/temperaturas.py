"""Validación de captura; no interpreta rangos clínicos ni simula sensores."""

from decimal import Decimal, InvalidOperation

from rest_framework.exceptions import ValidationError


def validar_temperatura(valor):
    try:
        temperatura = Decimal(str(valor))
        valida = (temperatura.is_finite() and abs(temperatura) <= Decimal("9999.99")
                  and temperatura == temperatura.quantize(Decimal("0.01")))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError({"temperatura_contenedor_c": "Debe registrar la temperatura del contenedor en °C."})
    if not valida:
        raise ValidationError({"temperatura_contenedor_c": "Ingrese un número finito con máximo dos decimales."})
    return temperatura.quantize(Decimal("0.01"))
