"""Tipos y cantidades de recipientes admitidos en la operación."""

from rest_framework.exceptions import ValidationError


TIPOS_RECIPIENTE = ("tubos", "frascos")


def validar_cantidades_recipientes(cantidad_tubos, cantidad_frascos=0):
    cantidades = {"cantidad_tubos": cantidad_tubos, "cantidad_frascos": cantidad_frascos}
    errores = {
        campo: "Debe indicar una cantidad entera entre 0 y 2147483647."
        for campo, valor in cantidades.items()
        if isinstance(valor, bool) or not isinstance(valor, int) or not 0 <= valor <= 2147483647
    }
    if errores:
        raise ValidationError(errores)
    if not any(cantidades.values()):
        raise ValidationError({campo: "Declare al menos un tubo o un frasco." for campo in cantidades})
    return cantidades
