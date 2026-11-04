"""Fuentes PDF incorporadas y sustitución explícita de glifos no disponibles."""

from functools import lru_cache
from html import escape
from pathlib import Path
import re
from threading import RLock

import reportlab
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


FUENTE_NORMAL = "VitaGoTexto"
FUENTE_NEGRITA = "VitaGoTextoNegrita"
_CERROJO = RLock()
_RECURSOS = Path(__file__).resolve().parent / "recursos/fuentes"


class _FuenteUnicode(TTFont):
    def addObjects(self, documento):
        # ReportLab 5.1 escribe los caracteres suplementarios como un entero
        # hexadecimal. ToUnicode necesita UTF-16BE, también para copiar/buscar.
        # Se corrigen solo los mapas creados por esta fuente en este documento;
        # no se modifica ninguna función ni configuración global de ReportLab.
        anteriores = set(documento.idToObject)
        super().addObjects(documento)
        for nombre in documento.idToObject.keys() - anteriores:
            if nombre.startswith("toUnicodeCMap:"):
                flujo = documento.idToObject[nombre]
                flujo.content = re.sub(
                    r"(<[0-9A-F]{2}>\s*)<([0-9A-F]{5,6})>",
                    lambda m: m[1] + "<" + chr(int(m[2], 16)).encode("utf-16-be").hex().upper() + ">",
                    flujo.content,
                )


@lru_cache(maxsize=1)
def registrar_fuentes():
    carpeta = Path(reportlab.__file__).resolve().parent / "fonts"
    with _CERROJO:
        for nombre, archivo in ((FUENTE_NORMAL, "Vera.ttf"), (FUENTE_NEGRITA, "VeraBd.ttf")):
            if nombre not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(_FuenteUnicode(nombre, str(carpeta / archivo)))


def _registrar_respaldo(nombre, archivo):
    with _CERROJO:
        if nombre not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(_FuenteUnicode(nombre, str(_RECURSOS / archivo)))
    return pdfmetrics.getFont(nombre)


@lru_cache(maxsize=2048)
def _fuente_caracter(caracter, base):
    if ord(caracter) in pdfmetrics.getFont(base).face.charWidths:
        return base
    respaldos = (("VitaGoCJK", "NotoSansSC-Regular.ttf"), ("VitaGoEmoji", "NotoEmoji-Regular.ttf"))
    if ord(caracter) > 0xFFFF:
        respaldos = respaldos[::-1]
    for nombre, archivo in respaldos:
        if ord(caracter) in _registrar_respaldo(nombre, archivo).face.charWidths:
            return nombre
    return None


def texto_pdf(texto, fuente=FUENTE_NORMAL):
    """Escapa texto de usuarios y agrupa los caracteres por fuente disponible."""
    registrar_fuentes()
    texto = texto.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
    glifos = pdfmetrics.getFont(fuente).face.charWidths
    if all(caracter == "\n" or ord(caracter) in glifos for caracter in set(texto)):
        return escape(texto).replace("\n", "<br/>")
    bloques, caracteres, actual = [], [], fuente

    def terminar():
        if caracteres:
            contenido = escape("".join(caracteres))
            bloques.append(contenido if actual == fuente else f'<font name="{actual}">{contenido}</font>')
            caracteres.clear()

    for caracter in texto:
        if caracter == "\n":
            terminar()
            bloques.append("<br/>")
            continue
        elegida = _fuente_caracter(caracter, fuente)
        representacion = caracter if elegida else f"[U+{ord(caracter):04X}]"
        elegida = elegida or fuente
        if elegida != actual:
            terminar()
            actual = elegida
        caracteres.append(representacion)
    terminar()
    return "".join(bloques)
