"""Identidad textual de departamentos registrados; no infiere geografía por GPS."""

from unicodedata import combining, normalize


def nombre_departamento(texto):
    return " ".join(normalize("NFC", texto or "").split())


def clave_departamento(texto):
    return "".join(c for c in normalize("NFKD", nombre_departamento(texto)) if not combining(c)).casefold()
