"""Una tabla por descarga, con el mismo contenido en Excel y PDF."""

from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from html import escape
from io import BytesIO
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle
from rest_framework.exceptions import ValidationError

from apps.reportes.fuentes import FUENTE_NORMAL, FUENTE_NEGRITA, registrar_fuentes, texto_pdf


COLOR = "D1393D"
COLOR_SECUNDARIO = "B92D33"
FONDO_ALTERNADO = "FBEAEC"
TEXTO_NORMAL = "333333"
TEXTO_SECUNDARIO = "595959"
_ESTILO_MEDICION_EXCEL = ParagraphStyle("MedicionExcel", fontName="Helvetica", fontSize=11, leading=15)
_RESUMEN = ("Motorista", "Empresa", "Placa", "Jornadas", "Completados", "Fallidos", "Cancelados", "Km GPS", "Temp. promedio °C")
_SERVICIOS = ("Motorista", "Empresa del servicio", "Solicitud", "Origen", "Destino", "Estado servicio / asignación",
              "Asignada en", "Fin de asignación", "Tubos", "Frascos")


def _tabla(datos):
    if datos["tipo"] == "motoristas":
        return "Resumen", _RESUMEN, (42, 30, 16, 14, 18, 14, 16, 16, 23), (56, 40, 22, 22, 26, 22, 25, 25, 28)
    return "Servicios", _SERVICIOS, (36, 26, 22, 30, 38, 28, 24, 24, 10, 10), (36, 25, 24, 33, 34, 28, 27, 27, 15, 17)


def _filas(datos):
    for motorista in datos["motoristas"]:
        if datos["tipo"] == "motoristas":
            r = motorista["resumen"]
            km, sol = r["kilometraje"], r["solicitudes"]
            temperatura = r["temperaturas"]["promedio_c"]
            yield motorista, [motorista["nombre"], motorista["empresa"], motorista["placa"],
                km["jornadas_cerradas"] + km["jornadas_sin_cierre_en_periodo"],
                sol["entregadas"], sol["fallidas"], sol["canceladas"],
                Decimal(km["kilometros_medidos"]) if km["kilometros_medidos"] is not None else None,
                Decimal(temperatura) if temperatura is not None else None], not km["completo"]
        else:
            for s in motorista["servicios"]:
                yield motorista, [motorista["nombre"], s["empresa"], s["numero"], s["origen"], s["destino"],
                    f'{s["estado_actual"]}\n{s["estado_asignacion"]}', s["asignada"], s["fin_asignacion"], s["tubos"], s["frascos"]], False


def _medir_texto_excel(texto, ancho):
    if "\n" not in texto and stringWidth(texto, "Helvetica", 11) <= ancho:
        return 28
    return Paragraph(escape(texto).replace("\n", "<br/>"), _ESTILO_MEDICION_EXCEL).wrap(ancho, 1000000)[1] + 8


def _altura_fila_excel(hoja, celdas, medir_texto):
    altura = 28
    for celda in celdas:
        if not isinstance(celda.value, str) or not celda.value:
            continue
        columna = hoja.column_dimensions[celda.column_letter]
        texto = celda.value.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
        ancho = max(8, (columna.width * 7 - 12) * 0.75)
        alto = medir_texto(texto, ancho)
        if alto > 409.5 and columna.width < 60:
            columna.width = 60
            alto = medir_texto(texto, (60 * 7 - 12) * 0.75)
        if alto > 409.5:
            raise ValidationError({"formato": "Un texto supera la altura máxima de Excel. Descargue el reporte en PDF para verlo completo."})
        altura = max(altura, alto)
    return altura


def _valor_excel(valor, zona):
    if isinstance(valor, datetime):
        return valor.astimezone(zona).replace(tzinfo=None)
    if isinstance(valor, str):
        valor = ILLEGAL_CHARACTERS_RE.sub("", valor)
        if len(valor) > 32767:
            raise ValidationError({"formato": "Un texto supera los 32767 caracteres por celda de Excel. Descargue el reporte en PDF."})
    return "N/D" if valor is None else valor


def exportar_excel(datos):
    nombre, columnas, anchos, _ = _tabla(datos)
    libro = Workbook()
    hoja = libro.active
    hoja.title = nombre
    hoja.sheet_view.showGridLines = False
    hoja.sheet_properties.tabColor = COLOR
    hoja.append([])
    hoja.append(["VitaGo | " + ("Resumen de motoristas" if datos["tipo"] == "motoristas" else "Servicios del día")])
    hoja.append([f'{datos["etiqueta"]} | {datos["fecha_desde"]} a {datos["fecha_hasta"]}'])
    hoja.append([datos["nota"]])
    hoja.append([])
    hoja.append(columnas)
    hoja["A2"].font = Font(name="Arial", size=14, bold=True, color=COLOR)
    for direccion in ("A3", "A4"):
        hoja[direccion].font = Font(name="Arial", size=10, italic=True, color=TEXTO_SECUNDARIO)
    hoja.row_dimensions[2].height = 26
    hoja.row_dimensions[6].height = 38
    hoja.freeze_panes = "D7" if datos["tipo"] == "motoristas" else "C7"
    for indice, ancho in enumerate(anchos, 1):
        hoja.column_dimensions[get_column_letter(indice)].width = ancho
    for celda in hoja[6]:
        celda.fill = PatternFill("solid", fgColor=COLOR)
        celda.font = Font(name="Arial", size=11, color="FFFFFF", bold=True)
        celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    medir_texto = lru_cache(maxsize=1024)(_medir_texto_excel)
    ultima = 6
    for motorista, fila, parcial in _filas(datos):
        hoja.append([_valor_excel(v, ZoneInfo(motorista["zona"])) for v in fila])
        ultima += 1
        celdas = next(hoja.iter_rows(min_row=ultima, max_row=ultima, min_col=1, max_col=len(columnas)))
        for celda in celdas:
            texto = isinstance(celda.value, str)
            if texto:
                celda.data_type = "s"  # Incluso un nombre que empieza con '=' es texto literal.
            if isinstance(celda.value, datetime):
                celda.number_format = "yyyy-mm-dd hh:mm:ss"
            elif isinstance(celda.value, date):
                celda.number_format = "yyyy-mm-dd"
            elif isinstance(celda.value, (float, Decimal)):
                celda.number_format = "0.00" if celda.column == 9 else r"0.000\ \*" if parcial else "0.000"
            celda.font = Font(name="Arial", size=11, color=TEXTO_NORMAL)
            celda.alignment = Alignment(horizontal="left" if texto and celda.value != "N/D" else "right", vertical="center", wrap_text=True)
            if ultima % 2:
                celda.fill = PatternFill("solid", fgColor=FONDO_ALTERNADO)
        hoja.row_dimensions[ultima].height = _altura_fila_excel(hoja, celdas, medir_texto)
    if ultima == 6:
        hoja.append(["Sin resultados dentro de los filtros y permisos indicados."])
        hoja.row_dimensions[7].height = 28
    hoja.auto_filter.ref = f"A6:{get_column_letter(len(columnas))}{ultima}"
    hoja.print_title_rows = "1:6"
    hoja.sheet_properties.pageSetUpPr.fitToPage = True
    hoja.page_setup.orientation = "landscape"
    hoja.page_setup.paperSize = hoja.PAPERSIZE_A4
    hoja.page_setup.fitToWidth, hoja.page_setup.fitToHeight = 1, 0
    salida = BytesIO()
    libro.save(salida)
    return salida.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class _ParrafoReporte(Paragraph):
    def wrap(self, ancho, alto):
        if ancho == getattr(self, "_ancho_calculado", None) and hasattr(self, "blPara"):
            return self.width, self.height
        resultado = super().wrap(ancho, alto)
        self._ancho_calculado = ancho if hasattr(self, "blPara") and resultado == (self.width, self.height) else None
        return resultado


def exportar_pdf(datos):
    registrar_fuentes()
    salida = BytesIO()
    estilos = {
        "dato": ParagraphStyle("Dato", fontName=FUENTE_NORMAL, fontSize=8, leading=11),
        "cabecera": ParagraphStyle("Cabecera", fontName=FUENTE_NEGRITA, fontSize=8, leading=11, textColor=colors.white),
        "titulo": ParagraphStyle("Titulo", fontName=FUENTE_NEGRITA, fontSize=17, leading=21, textColor=colors.HexColor("#"+COLOR)),
    }
    nombre, columnas, _, anchos = _tabla(datos)
    titulo = "Resumen de motoristas" if datos["tipo"] == "motoristas" else "Servicios del día"
    documento = SimpleDocTemplate(salida, pagesize=landscape(A4), leftMargin=14*mm, rightMargin=14*mm,
        topMargin=14*mm, bottomMargin=16*mm, title="VitaGo - " + titulo, author="VitaGo")

    def texto(valor, zona=None):
        if valor is None:
            return "N/D"
        if isinstance(valor, datetime):
            return valor.astimezone(zona).strftime("%d/%m/%Y %H:%M:%S")
        return str(valor)

    def parrafo(valor, estilo="dato"):
        return _ParrafoReporte(texto_pdf(str(valor), estilos[estilo].fontName), estilos[estilo])

    def tabla(encabezados, filas, anchuras, dividir=False):
        contenido = [[parrafo(c, "cabecera") for c in encabezados], *filas]
        t = LongTable(contenido, colWidths=[a*mm for a in anchuras], repeatRows=1, splitInRow=int(dividir), hAlign="LEFT")
        t.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#"+COLOR)),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#"+FONDO_ALTERNADO)]),
            ("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0), (-1,-1), 6),
            ("RIGHTPADDING", (0,0), (-1,-1), 6), ("TOPPADDING", (0,0), (-1,-1), 7), ("BOTTOMPADDING", (0,0), (-1,-1), 7)]))
        return t

    historia = [parrafo("VitaGo | " + titulo, "titulo"), Spacer(1, 3*mm),
        parrafo(f'{datos["etiqueta"]} | {datos["fecha_desde"]} a {datos["fecha_hasta"]}'),
        Spacer(1, 2*mm), parrafo(datos["nota"]), Spacer(1, 5*mm)]
    filas = []
    hubo_filas = False
    for motorista, valores, parcial in _filas(datos):
        hubo_filas = True
        zona = ZoneInfo(motorista["zona"])
        valores = [texto(v, zona) for v in valores]
        if datos["tipo"] == "motoristas" and parcial and valores[7] != "N/D":
            valores[7] += " *"
        celdas = [parrafo(v) for v in valores]
        # Las filas habituales comparten una tabla. Un texto extraordinariamente
        # largo usa una ficha con identificador repetido en cada continuación.
        altura = max(c.wrap(a*mm-12, 1000000)[1] for c, a in zip(celdas, anchos))
        if altura > 100*mm:
            if filas:
                historia.extend([tabla(columnas, filas, anchos), Spacer(1, 3*mm)])
                filas = []
            identificador = f"Solicitud {valores[2]}" if datos["tipo"] == "servicios" else f"Motorista {motorista['id']}"
            detalle = "\n".join(f"{c}: {v}" for c, v in zip(columnas, valores))
            historia.extend([tabla([identificador], [[parrafo(detalle)]], [266], dividir=True), Spacer(1, 3*mm)])
        else:
            filas.append(celdas)
    if filas:
        historia.append(tabla(columnas, filas, anchos))
    if not hubo_filas:
        historia.append(parrafo("Sin resultados dentro de los filtros y permisos indicados."))

    def pie(canvas, doc):
        canvas.saveState()
        canvas.setFont(FUENTE_NORMAL, 8)
        canvas.setFillColor(colors.HexColor("#"+COLOR_SECUNDARIO))
        canvas.drawString(14*mm, 9*mm, "VitaGo | Administración")
        canvas.drawRightString(283*mm, 9*mm, f"Página {doc.page}")
        canvas.restoreState()

    documento.build(historia, onFirstPage=pie, onLaterPages=pie)
    return salida.getvalue(), "application/pdf"
