"""Identidad de ambos exportadores, incluidos vacíos y continuaciones; sin BD."""

from collections import defaultdict
from datetime import date, datetime, timezone
from io import BytesIO
from unittest.mock import patch

from django.test import SimpleTestCase
from openpyxl import load_workbook
from reportlab.lib import colors
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph

from apps.reportes.exportadores import exportar_excel, exportar_pdf
from apps.reportes.fuentes import FUENTE_NEGRITA


_ANTERIORES = ("006A64", "EDF6F4", "52645E", "25332F")


def datos_ficticios(tipo, cantidad=2):
    fecha = date(2026, 10, 27)
    momento = datetime(2026, 10, 27, 16, tzinfo=timezone.utc)
    datos = {"tipo": tipo, "etiqueta": "Mensual · 2026-10" if tipo == "motoristas" else "Servicios · 2026-10-27",
        "fecha_desde": fecha.replace(day=1) if tipo == "motoristas" else fecha,
        "fecha_hasta": fecha.replace(day=31) if tipo == "motoristas" else fecha,
        "generado_en": momento, "nota": "Ejemplo ficticio para verificar la presentación.", "motoristas": []}
    for n in range(cantidad):
        motorista = {"id": f"DEMO-{n+1}", "nombre": f"María 漢字 🚚 Demostración {n+1:02d}",
            "empresa": "Empresa de demostración", "placa": "DEMO001", "zona": "America/Tegucigalpa"}
        if tipo == "motoristas":
            motorista["resumen"] = {"kilometraje": {"jornadas_cerradas": 12, "jornadas_sin_cierre_en_periodo": 0,
                "kilometros_medidos": "123.450", "completo": True},
                "solicitudes": {"entregadas": 20, "fallidas": 1, "canceladas": 2},
                "temperaturas": {"promedio_c": "4.25"}}
        else:
            motorista["servicios"] = [{"numero": f"SOL-DEMO-{n+1:04d}", "empresa": "Empresa de demostración",
                "origen": "Sucursal de origen", "destino": "Sucursal de destino", "estado_actual": "Entregada",
                "estado_asignacion": "Finalizada", "asignada": momento, "fin_asignacion": momento, "tubos": 8, "frascos": 2}]
        datos["motoristas"].append(motorista)
    return datos


def registrar_dibujo_pdf(datos):
    """Observa las instrucciones reales de dibujo, sin sustituir la generación."""
    parrafos, rellenos = defaultdict(list), defaultdict(list)
    dibujar, rellenar = Paragraph.draw, Canvas.setFillColor

    def parrafo(p):
        parrafos[p.canv.getPageNumber()].append((p.getPlainText(), p.style.textColor.rgb(), p.style.fontName))
        return dibujar(p)

    def relleno(canvas, color, *args, **kwargs):
        rellenos[canvas.getPageNumber()].append(colors.toColor(color).rgb())
        return rellenar(canvas, color, *args, **kwargs)

    with patch.object(Paragraph, "draw", parrafo), patch.object(Canvas, "setFillColor", relleno):
        contenido, mime = exportar_pdf(datos)
    return contenido, mime, parrafos, rellenos


class PruebasPaletaReportes(SimpleTestCase):
    def test_excel_colores_resumen_servicios_y_vacios(self):
        for tipo in ("motoristas", "servicios"):
            for cantidad in (0, 2):
                with self.subTest(tipo=tipo, cantidad=cantidad):
                    contenido, mime = exportar_excel(datos_ficticios(tipo, cantidad))
                    hoja = load_workbook(BytesIO(contenido)).active
                    self.assertIn("spreadsheetml.sheet", mime)
                    self.assertEqual(hoja.sheet_properties.tabColor.rgb[-6:], "D1393D")
                    self.assertEqual(hoja["A2"].font.color.rgb[-6:], "D1393D")
                    self.assertEqual(hoja["A3"].font.color.rgb[-6:], "595959")
                    usados = {hoja.sheet_properties.tabColor.rgb[-6:]}
                    for celda in hoja[6]:
                        self.assertEqual(celda.fill.fgColor.rgb[-6:], "D1393D")
                        self.assertEqual(celda.font.color.rgb[-6:], "FFFFFF")
                        self.assertTrue(celda.font.bold)
                    if cantidad:
                        self.assertEqual(hoja["A7"].fill.fgColor.rgb[-6:], "FBEAEC")
                        self.assertEqual(hoja["A7"].font.color.rgb[-6:], "333333")
                    for fila in hoja:
                        for celda in fila:
                            for color in (celda.font.color, celda.fill.fgColor, celda.fill.bgColor,
                                          *[getattr(celda.border, lado).color for lado in ("left", "right", "top", "bottom")]):
                                if color is not None and color.type == "rgb":
                                    usados.add(color.rgb[-6:])
                    self.assertFalse(usados.intersection(_ANTERIORES), usados)

    def test_pdf_colores_y_texto_blanco_en_ambos_reportes_y_vacios(self):
        rojo, oscuro, claro = [colors.HexColor("#"+c).rgb() for c in ("D1393D", "B92D33", "FBEAEC")]
        anteriores = {colors.HexColor("#"+c).rgb() for c in _ANTERIORES}
        for tipo in ("motoristas", "servicios"):
            for cantidad in (0, 2):
                with self.subTest(tipo=tipo, cantidad=cantidad):
                    contenido, mime, parrafos, rellenos = registrar_dibujo_pdf(datos_ficticios(tipo, cantidad))
                    self.assertTrue(contenido.startswith(b"%PDF-"))
                    self.assertEqual(mime, "application/pdf")
                    usados = {c for pagina in rellenos.values() for c in pagina}
                    self.assertTrue({rojo, oscuro}.issubset(usados))
                    self.assertFalse(usados.intersection(anteriores))
                    titulos = [p for pagina in parrafos.values() for p in pagina if p[0].startswith("VitaGo |")]
                    self.assertEqual(len(titulos), 1)
                    self.assertEqual(titulos[0][1], rojo)
                    if cantidad:
                        self.assertIn(claro, usados)
                        cabeceras = [p for pagina in parrafos.values() for p in pagina if p[0] == "Motorista"]
                        self.assertTrue(cabeceras)
                        self.assertTrue(all(p[1:] == ((1, 1, 1), FUENTE_NEGRITA) for p in cabeceras))

    def test_pdf_encabezados_rojos_repetidos_en_continuaciones_de_ambos_reportes(self):
        rojo = colors.HexColor("#D1393D").rgb()
        for tipo in ("motoristas", "servicios"):
            with self.subTest(tipo=tipo):
                _, _, paginas, rellenos = registrar_dibujo_pdf(datos_ficticios(tipo, 40))
                self.assertGreater(len(paginas), 1)
                for numero, parrafos in paginas.items():
                    self.assertIn(("Motorista", (1, 1, 1), FUENTE_NEGRITA), parrafos)
                    self.assertIn(rojo, rellenos[numero])

    def test_pdf_ficha_extensa_repite_identificador_blanco_y_fondo_rojo(self):
        datos = datos_ficticios("servicios", 1)
        datos["motoristas"][0]["servicios"][0]["destino"] = "CONTENIDO DE DEMOSTRACIÓN DEL DESTINO " * 400
        _, _, paginas, rellenos = registrar_dibujo_pdf(datos)
        self.assertGreater(len(paginas), 1)
        for numero, parrafos in paginas.items():
            if any("CONTENIDO DE DEMOSTRACIÓN" in p[0] for p in parrafos):
                self.assertIn(("Solicitud SOL-DEMO-0001", (1, 1, 1), FUENTE_NEGRITA), parrafos)
                self.assertIn(colors.HexColor("#D1393D").rgb(), rellenos[numero])

    def test_contraste_de_encabezados_reales_supera_minimo_aa(self):
        def luminancia(hexadecimal):
            canales = [int(hexadecimal[i:i+2], 16)/255 for i in (0, 2, 4)]
            lineales = [c/12.92 if c <= 0.04045 else ((c+0.055)/1.055)**2.4 for c in canales]
            return sum(c*peso for c, peso in zip(lineales, (0.2126, 0.7152, 0.0722)))

        for tipo in ("motoristas", "servicios"):
            contenido, _ = exportar_excel(datos_ficticios(tipo))
            celda = load_workbook(BytesIO(contenido)).active["A6"]
            claro, oscuro = sorted((luminancia(celda.font.color.rgb[-6:]), luminancia(celda.fill.fgColor.rgb[-6:])), reverse=True)
            self.assertGreaterEqual((claro+0.05)/(oscuro+0.05), 4.5)
