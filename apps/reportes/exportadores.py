"""Dos formatos sobre el mismo reporte; sin consultas ni llamadas a proveedores."""

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
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import LongTable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, TableStyle
from rest_framework.exceptions import ValidationError

from apps.reportes.fuentes import FUENTE_NORMAL, FUENTE_NEGRITA, registrar_fuentes, texto_pdf


COLOR = "006A64"
_ESTILO_MEDICION_EXCEL = ParagraphStyle("MedicionExcel", fontName="Helvetica", fontSize=11, leading=15)


def _medir_texto_excel(texto, ancho):
    if "\n" not in texto and stringWidth(texto, "Helvetica", 11) <= ancho:
        return 45
    parrafo = Paragraph(escape(texto).replace("\n", "<br/>"), _ESTILO_MEDICION_EXCEL)
    return parrafo.wrap(ancho, 1000000)[1] + 6


def _altura_fila_excel(hoja, celdas, medir_texto):
    altura = 45
    for celda in celdas:
        if not isinstance(celda.value, str) or not celda.value:
            continue
        columna = hoja.column_dimensions[celda.column_letter]
        texto = celda.value.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
        # Unidades de ancho Excel a puntos, con margen para Calibri y sus
        # sustitutos. Paragraph calcula el ajuste por palabras y saltos de línea.
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
    return valor


def _tablas(motorista):
    r = motorista["resumen"]
    km, sol, tubos, frascos, temp = (r[c] for c in ("kilometraje", "solicitudes", "tubos", "frascos", "temperaturas"))
    yield "Resumen", (
        "Asignadas", "Recolectadas", "Entregadas", "Fallidas", "Canceladas", "Tubos recogidos", "Tubos entregados",
        "Frascos recogidos", "Frascos entregados", "Recolecciones sin tubos", "Recolecciones sin frascos",
        "Km GPS medidos", "Km GPS consolidados", "Jornadas cerradas", "Jornadas con medición", "Jornadas consolidadas",
        "Jornadas sin cierre en período", "Kilometraje completo", "Temperatura mínima °C", "Temperatura máxima °C",
        "Temperatura promedio °C", "Lecturas sin temperatura", "Desvíos detectados", "Perfil activo",
    ), [[sol["asignadas"], sol["recolectadas"], sol["entregadas"], sol["fallidas"], sol["canceladas"],
         tubos["recogidos_conocidos"], tubos["entregados_conocidos"], frascos["recogidos_conocidos"], frascos["entregados_conocidos"],
         tubos["recolecciones_sin_cantidad"], frascos["recolecciones_sin_cantidad"],
         *[Decimal(km[c]) if km[c] is not None else None for c in ("kilometros_medidos", "kilometros_consolidados")],
         km["jornadas_cerradas"], km["jornadas_con_medicion"], km["jornadas_consolidadas"], km["jornadas_sin_cierre_en_periodo"],
         km["completo"], *[Decimal(temp[c]) if temp[c] is not None else None for c in ("minima_c", "maxima_c", "promedio_c")],
         temp["lecturas_sin_temperatura"], len(motorista["desviaciones"]), motorista["activo"]]]
    yield "Jornadas", ("Fecha operativa", "Inicio", "Fin", "Estado", "Km GPS", "Calidad GPS", "Minutos activos",
                       "Minutos operativos", "Minutos de almuerzo", "Servicios completados"), [
        [j[c] for c in ("fecha", "inicio", "fin", "estado", "km", "calidad", "minutos_activos", "minutos_operativos", "minutos_almuerzo", "entregas")]
        for j in motorista["jornadas"]]
    yield "Servicios", ("Solicitud", "Empresa del servicio", "Sucursal", "Solicitante", "Origen", "Destino", "Modalidad", "Prioridad",
                        "Estado actual del servicio", "Estado de asignación", "Asignada en", "Fin de asignación", "Tubos", "Frascos"), [
        [s[c] for c in ("numero", "empresa", "sucursal", "solicitante", "origen", "destino", "modalidad", "prioridad", "estado_actual",
                       "estado_asignacion", "asignada", "fin_asignacion", "tubos", "frascos")] for s in motorista["servicios"]]
    yield "Temperaturas", ("Solicitud", "Registrada en", "Temperatura °C", "Fuente"), [
        [t[c] for c in ("solicitud", "fecha", "temperatura", "fuente")] for t in motorista["temperaturas"]]
    yield "Desvíos", ("Solicitud", "Etapa", "Detectado en", "Cerrado en", "Motivo de cierre"), [
        [a[c] for c in ("solicitud", "etapa", "detectada", "fin", "motivo_cierre")] for a in motorista["desviaciones"]]


def exportar_excel(datos):
    libro = Workbook()
    libro.remove(libro.active)
    filas_hoja = {}
    alineacion = Alignment(vertical="top", wrap_text=True)
    # Caché acotada a esta descarga; no retiene textos de otros usuarios.
    medir_texto = lru_cache(maxsize=1024)(_medir_texto_excel)
    # Los encabezados se obtienen del primer motorista; sin resultados se usa
    # una hoja informativa para no inventar filas ni métricas.
    if not datos["motoristas"]:
        hoja = libro.create_sheet("Resumen")
        hoja.append(["VitaGo - Reporte de motoristas"])
        hoja.append(["No hay motoristas dentro de los filtros y permisos indicados."])
        hoja.append([f'{datos["fecha_desde"]} a {datos["fecha_hasta"]}; generado {datos["generado_en"].isoformat()}'])
        hoja.append([datos["nota"]])
        hoja.column_dimensions["A"].width = 100
        hoja["A4"].alignment = Alignment(wrap_text=True)
        hoja.row_dimensions[4].height = 60
    for motorista in datos["motoristas"]:
        zona = ZoneInfo(motorista["zona"])
        for nombre, columnas, filas in _tablas(motorista):
            if nombre not in libro.sheetnames:
                hoja = libro.create_sheet(nombre)
                hoja.append(["VitaGo - " + nombre])
                hoja.append([f'{datos["fecha_desde"]} a {datos["fecha_hasta"]}; generado {datos["generado_en"].isoformat()}'])
                hoja.append([datos["nota"]])
                hoja.append([])
                hoja.append(["Motorista", "Empresa de flota", "Placa", "Zona horaria", *columnas])
                filas_hoja[nombre] = 5
                hoja.merge_cells(start_row=1, start_column=1, end_row=1, end_column=4 + len(columnas))
                hoja.merge_cells(start_row=2, start_column=1, end_row=2, end_column=4 + len(columnas))
                hoja.merge_cells(start_row=3, start_column=1, end_row=3, end_column=4 + len(columnas))
                hoja["A1"].font = Font(size=16, bold=True, color=COLOR)
                hoja["A3"].alignment = Alignment(wrap_text=True, vertical="top")
                hoja.row_dimensions[3].height = 45
                hoja.row_dimensions[5].height = 42
                hoja.freeze_panes = "E6"
                hoja.sheet_view.showGridLines = False
                for celda in hoja[5]:
                    celda.fill = PatternFill("solid", fgColor=COLOR)
                    celda.font = Font(color="FFFFFF", bold=True)
                    celda.alignment = Alignment(wrap_text=True, vertical="center")
                for indice, encabezado in enumerate(["Motorista", "Empresa de flota", "Placa", "Zona horaria", *columnas], 1):
                    hoja.column_dimensions[get_column_letter(indice)].width = 30 if indice in (1, 2, 4) else min(38, max(16, len(encabezado)))
            hoja = libro[nombre]
            for fila in filas:
                valores = [motorista["nombre"], motorista["empresa"], motorista["placa"], motorista["zona"], *fila]
                hoja.append([_valor_excel(v, zona) for v in valores])
                filas_hoja[nombre] += 1
                numero_fila = filas_hoja[nombre]
                celdas = next(hoja.iter_rows(min_row=numero_fila, max_row=numero_fila, min_col=1, max_col=len(valores)))
                for celda in celdas:
                    if isinstance(celda.value, str):
                        celda.data_type = "s"  # Un nombre que empieza con '=' nunca se ejecuta como fórmula.
                    if isinstance(celda.value, datetime):
                        celda.number_format = "yyyy-mm-dd hh:mm:ss"
                    elif isinstance(celda.value, date):
                        celda.number_format = "yyyy-mm-dd"
                    elif isinstance(celda.value, (float, Decimal)):
                        celda.number_format = "0.000"
                    celda.alignment = alineacion
                hoja.row_dimensions[numero_fila].height = _altura_fila_excel(hoja, celdas, medir_texto)
    for hoja in libro:
        if hoja.max_row >= 5:
            hoja.auto_filter.ref = f"A5:{get_column_letter(hoja.max_column)}{hoja.max_row}"
    salida = BytesIO()
    libro.save(salida)
    return salida.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class _ParrafoReporte(Paragraph):
    def wrap(self, ancho, alto):
        # Las tablas miden varias veces el mismo párrafo. El cálculo de líneas
        # depende del ancho, no del alto; split puede invalidarlo al borrar blPara.
        if ancho == getattr(self, "_ancho_calculado", None) and hasattr(self, "blPara"):
            return self.width, self.height
        resultado = super().wrap(ancho, alto)
        self._ancho_calculado = ancho if hasattr(self, "blPara") and resultado == (self.width, self.height) else None
        return resultado


def exportar_pdf(datos):
    salida = BytesIO()
    registrar_fuentes()
    estilos = getSampleStyleSheet()
    for estilo in estilos.byName.values():
        if isinstance(estilo, ParagraphStyle):
            estilo.fontName = FUENTE_NEGRITA if "Bold" in estilo.fontName else FUENTE_NORMAL
    estilos.add(ParagraphStyle(name="Dato", fontName=FUENTE_NORMAL, fontSize=8, leading=11, spaceAfter=4))
    estilos.add(ParagraphStyle(name="CabeceraTabla", parent=estilos["Dato"], textColor=colors.white, fontName=FUENTE_NEGRITA))
    estilos["Heading1"].textColor = colors.HexColor("#" + COLOR)
    estilos["Heading2"].keepWithNext = True
    documento = SimpleDocTemplate(salida, pagesize=landscape(A4), leftMargin=14*mm, rightMargin=14*mm,
                                 topMargin=14*mm, bottomMargin=16*mm, title="VitaGo - Reporte operativo de motoristas", author="VitaGo")

    def parrafo(valor, estilo="Dato", zona=None):
        if valor is None:
            valor = "N/D"
        elif isinstance(valor, datetime):
            valor = valor.astimezone(zona).strftime("%d/%m/%Y %H:%M:%S") if zona else valor.isoformat()
        elif isinstance(valor, date):
            valor = valor.strftime("%d/%m/%Y")
        elif isinstance(valor, bool):
            valor = "Sí" if valor else "No"
        return _ParrafoReporte(texto_pdf(str(valor), estilos[estilo].fontName), estilos[estilo])

    def tabla(encabezados, filas, anchos, zona, titulo=None):
        contenido = [[parrafo(titulo, "Heading2"), *[""] * (len(encabezados)-1)]] if titulo else []
        fila_cabecera = len(contenido)
        contenido.append([parrafo(c, "CabeceraTabla") for c in encabezados])
        contenido.extend([parrafo(c, zona=zona) for c in fila] for fila in filas)
        tabla = LongTable(contenido, colWidths=[a*mm for a in anchos], repeatRows=fila_cabecera+1, splitInRow=1, hAlign="LEFT")
        tabla.setStyle(TableStyle([("BACKGROUND", (0,fila_cabecera), (-1,fila_cabecera), colors.HexColor("#"+COLOR)),
            ("ROWBACKGROUNDS", (0,fila_cabecera+1), (-1,-1), [colors.white, colors.HexColor("#EDF6F4")]),
            ("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0), (-1,-1), 6),
            ("RIGHTPADDING", (0,0), (-1,-1), 6), ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6)]))
        return tabla

    historia = [parrafo("VitaGo | Reporte operativo", "Title"),
        parrafo(f'Período: {datos["fecha_desde"]} a {datos["fecha_hasta"]} | Generado: {datos["generado_en"].isoformat()}'),
        parrafo(datos["nota"]), Spacer(1, 5*mm)]
    if not datos["motoristas"]:
        historia.append(parrafo("No hay motoristas dentro de los filtros y permisos indicados."))
    for indice, motorista in enumerate(datos["motoristas"]):
        if indice:
            historia.append(PageBreak())
        zona, resumen = ZoneInfo(motorista["zona"]), motorista["resumen"]
        historia.extend([parrafo(motorista["nombre"], "Heading1"),
            parrafo(f'{motorista["empresa"]} | Placa: {motorista["placa"] or "N/D"} | Zona horaria: {motorista["zona"]} | Perfil activo: {"Sí" if motorista["activo"] else "No"}')])
        sol, km = resumen["solicitudes"], resumen["kilometraje"]
        historia.append(tabla(["Asignadas", "Recolectadas", "Entregadas", "Fallidas", "Canceladas", "Km GPS", "Km consolidados"],
            [[sol[c] for c in ("asignadas", "recolectadas", "entregadas", "fallidas", "canceladas")]
             + [km["kilometros_medidos"], km["kilometros_consolidados"]]], [38]*7, zona))
        historia.append(parrafo(f'Jornadas cerradas: {km["jornadas_cerradas"]}. Sin cierre en período: {km["jornadas_sin_cierre_en_periodo"]}. '
                               f'Kilometraje completo: {"Sí" if km["completo"] else "No"}.'))
        tubos, frascos, temp = (resumen[c] for c in ("tubos", "frascos", "temperaturas"))
        historia.append(tabla(["Tubos recogidos / entregados", "Frascos recogidos / entregados", "Temperatura mínima / máxima / promedio °C"],
            [[f'{tubos["recogidos_conocidos"]} / {tubos["entregados_conocidos"]}',
              f'{frascos["recogidos_conocidos"]} / {frascos["entregados_conocidos"]}',
              ' / '.join(temp[c] or "N/D" for c in ("minima_c", "maxima_c", "promedio_c"))]], [80,80,106], zona))
        historia.append(parrafo(f'Recolecciones sin cantidad de tubos: {tubos["recolecciones_sin_cantidad"]}. '
                               f'Sin cantidad de frascos: {frascos["recolecciones_sin_cantidad"]}. '
                               f'Lecturas sin temperatura: {temp["lecturas_sin_temperatura"]}. Desvíos detectados: {len(motorista["desviaciones"])}.'))
        for nombre, encabezados, filas in _tablas(motorista):
            if nombre == "Resumen":
                continue
            if nombre != "Servicios" or not filas:
                historia.append(parrafo(nombre, "Heading2"))
            if not filas:
                historia.append(parrafo("Sin registros en el período."))
            elif nombre == "Servicios":
                for indice_servicio, fila in enumerate(filas):
                    detalle = "\n".join(f"{c}: {v if v is not None else 'N/D'}" for c, v in zip(encabezados[1:],
                        [v.astimezone(zona).strftime('%d/%m/%Y %H:%M:%S') if isinstance(v, datetime) else v for v in fila[1:]]))
                    # Cada servicio conserva su identificador como encabezado
                    # repetido incluso si un detalle muy largo ocupa varias páginas.
                    historia.append(tabla([f"Solicitud {fila[0]}"], [[detalle]], [266], zona,
                                          titulo="Servicios" if indice_servicio == 0 else None))
                    historia.append(Spacer(1, 2*mm))
            elif nombre == "Jornadas":
                historia.append(tabla(["Fecha", "Inicio / Fin", "Estado / Calidad", "Km GPS", "Min. activos / operativos / almuerzo", "Completados"],
                    [[f[0], f'{parrafo(f[1],zona=zona).getPlainText()}\n{parrafo(f[2],zona=zona).getPlainText()}', f'{f[3]}\n{f[5]}',
                      f[4], ' / '.join('N/D' if v is None else str(v) for v in f[6:9]), f[9]] for f in filas], [25,48,50,25,83,35], zona))
            else:
                historia.append(tabla(encabezados, filas, [266/len(encabezados)]*len(encabezados), zona))
        historia.append(Spacer(1, 4*mm))

    def pie(canvas, doc):
        canvas.saveState()
        canvas.setFont(FUENTE_NORMAL, 8)
        canvas.setFillColor(colors.HexColor("#52645E"))
        canvas.drawString(14*mm, 9*mm, "VitaGo | Información operativa para administración")
        canvas.drawRightString(283*mm, 9*mm, f"Página {doc.page}")
        canvas.restoreState()

    documento.build(historia, onFirstPage=pie, onLaterPages=pie)
    return salida.getvalue(), "application/pdf"
