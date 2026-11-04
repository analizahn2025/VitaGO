from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

from apps.organizaciones.models import Empresa
from apps.organizaciones.models import Sucursal
from apps.reportes.selectores import construir_reporte_motoristas
from apps.reportes.fuentes import _FuenteUnicode, texto_pdf
from apps.reportes.exportadores import exportar_excel, _ParrafoReporte
from apps.repartidores.tests import test_resumenes as datos


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasReportesMotoristas(TestCase):
    setUpTestData = classmethod(datos.PruebasResumenesMotoristas.setUpTestData.__func__)
    setUp = datos.PruebasResumenesMotoristas.setUp
    _solicitud = datos.PruebasResumenesMotoristas._solicitud
    _jornada = datos.PruebasResumenesMotoristas._jornada
    _lector = datos.PruebasResumenesMotoristas._lector
    _lectura = datos.PruebasResumenesMotoristas._lectura

    def _descargar(self, **opciones):
        return self.cliente.get(reverse("reportes:motoristas-descargar"), {
            "fecha_desde": str(self.fecha), "fecha_hasta": str(self.fecha), **opciones})

    def test_excel_valido_con_hojas_orden_fechas_y_sin_duplicar_km_por_envios(self):
        self._solicitud(); self._solicitud()
        self._jornada("8.250")
        respuesta = self._descargar(repartidor_id=self.repartidor.pk)
        self.assertEqual(respuesta.status_code, 200, getattr(respuesta, "data", None))
        self.assertIn("attachment;", respuesta["Content-Disposition"])
        self.assertIn("no-store", respuesta["Cache-Control"])
        libro = load_workbook(BytesIO(respuesta.content), data_only=False)
        self.assertEqual(libro.sheetnames, ["Resumen", "Jornadas", "Servicios", "Temperaturas", "Desvíos"])
        resumen = dict(zip([c.value for c in libro["Resumen"][5]], [c.value for c in libro["Resumen"][6]]))
        self.assertEqual(resumen["Entregadas"], 2)
        self.assertEqual(resumen["Km GPS medidos"], 8.250)
        self.assertEqual(resumen["Km GPS consolidados"], 8.250)
        self.assertIsNone(libro["Jornadas"]["F6"].value.tzinfo)
        self.assertEqual(libro["Resumen"].freeze_panes, "E6")

    def test_pdf_es_descargable_y_tiene_estructura_valida(self):
        self._solicitud(); self._jornada()
        respuesta = self._descargar(formato="pdf", repartidor_id=self.repartidor.pk)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta["Content-Type"], "application/pdf")
        self.assertTrue(respuesta.content.startswith(b"%PDF-"))
        self.assertIn(b"%%EOF", respuesta.content)
        self.assertIn(b"/Type /Page", respuesta.content)

    def test_periodo_de_varios_dias_suma_jornadas_sin_duplicarlas(self):
        self._jornada("2.500")
        self._jornada("4.000", finalizada=self.inicio + timedelta(days=1, hours=4))
        reporte = construir_reporte_motoristas(self.administrador, {"repartidor_id": self.repartidor.pk,
            "fecha_desde": self.fecha, "fecha_hasta": self.fecha + timedelta(days=1)}, ahora=self.ahora)
        self.assertEqual(reporte["motoristas"][0]["resumen"]["kilometraje"]["kilometros_consolidados"], "6.500")

    def test_medicion_ausente_se_conserva_como_desconocida(self):
        self._jornada(disponible=False, calidad="SIN_VERIFICAR")
        datos = construir_reporte_motoristas(self.administrador, {"fecha_desde": self.fecha, "repartidor_id": self.repartidor.pk})
        motorista = datos["motoristas"][0]
        self.assertIsNone(motorista["resumen"]["kilometraje"]["kilometros_medidos"])
        self.assertIsNone(motorista["jornadas"][0]["km"])

    def test_lector_sin_todos_los_permisos_no_descarga(self):
        self.cliente.force_authenticate(self._lector(permisos=("reporte.ver",)))
        self.assertEqual(self._descargar().status_code, 403)

    def test_lector_de_sucursal_no_puede_exportar_historial_completo(self):
        sucursal = Sucursal.objects.create(empresa=self.empresa, ubicacion=self.origen, nombre="Sucursal de prueba", codigo="REPORTE")
        self.cliente.force_authenticate(self._lector(sucursal=sucursal))
        respuesta = self._descargar()
        self.assertEqual(respuesta.status_code, 200)
        libro = load_workbook(BytesIO(respuesta.content))
        self.assertIn("No hay motoristas", libro["Resumen"]["A2"].value)

    def test_otra_empresa_no_ve_motoristas_ni_servicios_ajenos(self):
        self._solicitud()
        otra = Empresa.objects.create(nombre="Otra empresa", pais=self.pais)
        self.cliente.force_authenticate(self._lector(empresa=otra))
        r = self._descargar(empresa_id=self.empresa.pk)
        self.assertEqual(r.status_code, 200)
        libro = load_workbook(BytesIO(r.content))
        self.assertEqual(libro.sheetnames, ["Resumen"])
        self.assertIn("No hay motoristas", libro["Resumen"]["A2"].value)

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_admin_exporta_flota_compartida_y_cliente_no_accede(self):
        from apps.repartidores.models import Repartidor
        from apps.usuarios.models import Usuario
        Repartidor.objects.filter(pk=self.repartidor.pk).update(empresa=None)
        Usuario.objetos.filter(pk=self.repartidor.usuario_id).update(empresa=None)
        r = self._descargar(repartidor_id=self.repartidor.pk)
        self.assertEqual(r.status_code, 200)
        libro = load_workbook(BytesIO(r.content))
        self.assertEqual(libro["Resumen"]["B6"].value, "Network - flota compartida")
        self.cliente.force_authenticate(self._lector())
        r = self._descargar(repartidor_id=self.repartidor.pk)
        libro = load_workbook(BytesIO(r.content))
        self.assertIn("No hay motoristas", libro["Resumen"]["A2"].value)

    def test_inyeccion_de_formulas_se_exporta_siempre_como_texto(self):
        self.repartidor.usuario.nombres = "=1+1"
        self.repartidor.usuario.save(update_fields=("nombres",))
        r = self._descargar(repartidor_id=self.repartidor.pk)
        libro = load_workbook(BytesIO(r.content), data_only=False)
        self.assertTrue(libro["Resumen"]["A6"].value.startswith("=1+1"))
        self.assertEqual(libro["Resumen"]["A6"].data_type, "s")

    def test_validaciones_conservan_nombres_de_campo(self):
        for opciones, campo in (({"fecha_hasta": "2026-10-26"}, "fecha_hasta"),
            ({"fecha_hasta": "2026-12-01"}, "fecha_hasta"), ({"formato": "csv"}, "formato"),
            ({"fecha_desde": "9999-12-31", "fecha_hasta": "9999-12-31"}, "fecha_desde"),
            ({"otro": "valor"}, "otro")):
            r = self._descargar(**opciones)
            self.assertEqual(r.status_code, 400, opciones)
            self.assertIn(campo, r.data)

    def test_sin_autenticacion_no_descarga(self):
        self.cliente.force_authenticate(None)
        self.assertEqual(self._descargar().status_code, 401)

    def test_accept_binario_permite_descarga_y_conserva_errores_json(self):
        url = reverse("reportes:motoristas-descargar")
        r = self.cliente.get(url, {"formato": "pdf", "repartidor_id": self.repartidor.pk}, HTTP_ACCEPT="application/pdf")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b"%PDF-"))
        error = self.cliente.get(url, {"formato": "invalido"}, HTTP_ACCEPT="application/pdf")
        self.assertEqual(error.status_code, 400)
        self.assertIn("application/json", error["Content-Type"])
        self.assertIn("formato", error.json())

    def test_todas_las_temperaturas_se_exportan_sin_contenido_de_imagen(self):
        self._lectura("4.50")
        r = self._descargar(repartidor_id=self.repartidor.pk)
        libro = load_workbook(BytesIO(r.content))
        self.assertEqual(libro["Temperaturas"]["G6"].value, 4.5)
        self.assertEqual(libro["Temperaturas"]["H6"].value, "MANUAL")

    def test_excel_muestra_nombre_largo_completo_en_resumen_y_detalles(self):
        usuario = self.repartidor.usuario
        usuario.nombres = "María Alejandra " * 9
        usuario.apellidos = "Hernández Martínez " * 7
        usuario.save(update_fields=("nombres", "apellidos"))
        self._solicitud()
        self._jornada()
        respuesta = self._descargar(repartidor_id=self.repartidor.pk)
        self.assertEqual(respuesta.status_code, 200)
        libro = load_workbook(BytesIO(respuesta.content))
        for nombre in ("Resumen", "Jornadas", "Servicios"):
            self.assertEqual(libro[nombre]["A6"].value, f"{usuario.nombres} {usuario.apellidos}".strip())
            self.assertGreater(libro[nombre].row_dimensions[6].height, 45)
            self.assertLessEqual(libro[nombre].row_dimensions[6].height, 409.5)

    def test_excel_respeta_saltos_de_linea_en_texto(self):
        usuario = self.repartidor.usuario
        usuario.nombres = "\n".join(["Nombre"] * 6)
        usuario.save(update_fields=("nombres",))
        respuesta = self._descargar(repartidor_id=self.repartidor.pk)
        self.assertEqual(respuesta.status_code, 200)
        libro = load_workbook(BytesIO(respuesta.content))
        self.assertIn(usuario.nombres, libro["Resumen"]["A6"].value)
        self.assertGreaterEqual(libro["Resumen"].row_dimensions[6].height, 90)

    def _destino_especial(self, solicitud, texto):
        type(solicitud).objects.filter(pk=solicitud.pk).update(
            modalidad="ESPECIAL", destino=None, destino_especial=texto,
        )

    def test_excel_admite_descripcion_extensa_ajustando_ancho_y_altura(self):
        solicitud = self._solicitud()
        texto = "Detalle del destino especial de demostración " * 24
        self._destino_especial(solicitud, texto)
        respuesta = self._descargar(repartidor_id=self.repartidor.pk)
        self.assertEqual(respuesta.status_code, 200, getattr(respuesta, "data", None))
        hoja = load_workbook(BytesIO(respuesta.content))["Servicios"]
        self.assertEqual(hoja["J6"].value, texto)
        self.assertLessEqual(hoja.row_dimensions[6].height, 409.5)
        self.assertGreater(hoja.row_dimensions[6].height, 45)

    def test_excel_no_trunca_textos_ni_oculta_filas_imposibles(self):
        solicitud = self._solicitud()
        for texto in ("x" * 32768, "\n".join(["Texto"] * 100)):
            self._destino_especial(solicitud, texto)
            respuesta = self._descargar(repartidor_id=self.repartidor.pk)
            self.assertEqual(respuesta.status_code, 400)
            self.assertIn("formato", respuesta.data)
            self.assertIn("PDF", str(respuesta.data["formato"]))

    def test_pdf_identifica_servicio_en_todas_sus_paginas(self):
        solicitud = self._solicitud()
        self._destino_especial(solicitud, "CONTENIDO DEL DESTINO ESPECIAL " * 400)
        paginas = {}
        dibujar = Paragraph.draw

        def registrar(parrafo):
            paginas.setdefault(parrafo.canv.getPageNumber(), []).append(parrafo.getPlainText())
            return dibujar(parrafo)

        with patch.object(Paragraph, "draw", registrar):
            respuesta = self._descargar(formato="pdf", repartidor_id=self.repartidor.pk)
        self.assertEqual(respuesta.status_code, 200)
        continuaciones = [textos for textos in paginas.values() if any("CONTENIDO DEL DESTINO" in t for t in textos)]
        self.assertGreaterEqual(len(continuaciones), 2)
        for textos in continuaciones:
            self.assertIn(f"Solicitud {solicitud.numero}", textos)

    def test_pdf_incorpora_caracteres_chinos_y_emoji_con_mapa_unicode_valido(self):
        usuario = self.repartidor.usuario
        usuario.nombres = "María 漢字 🚚"
        usuario.save(update_fields=("nombres",))
        mapas = []
        agregar = _FuenteUnicode.addObjects

        def registrar(fuente, documento):
            agregar(fuente, documento)
            mapas.extend(objeto.content for nombre, objeto in documento.idToObject.items()
                         if nombre.startswith("toUnicodeCMap:"))

        with patch.object(_FuenteUnicode, "addObjects", registrar):
            respuesta = self._descargar(formato="pdf", repartidor_id=self.repartidor.pk)
        self.assertEqual(respuesta.status_code, 200)
        contenido = "\n".join(mapas)
        for codigo in ("<6F22>", "<5B57>", "<D83DDE9A>"):
            self.assertIn(codigo, contenido)

    def test_pdf_identifica_glifo_no_disponible_y_escapa_marcado(self):
        contenido = texto_pdf("Texto <b>literal</b> \u0378")
        self.assertIn("&lt;b&gt;literal&lt;/b&gt;", contenido)
        self.assertIn("[U+0378]", contenido)

    def test_pdf_titulo_de_seccion_permanece_junto_a_su_contenido(self):
        usuario = self.repartidor.usuario
        usuario.nombres = "María Alejandra " * 9
        usuario.apellidos = "Hernández Martínez " * 7
        usuario.save(update_fields=("nombres", "apellidos"))
        solicitud = self._solicitud()
        self._jornada()
        paginas = {}
        dibujar = Paragraph.draw

        def registrar(parrafo):
            paginas.setdefault(parrafo.canv.getPageNumber(), []).append(parrafo.getPlainText())
            return dibujar(parrafo)

        with patch.object(Paragraph, "draw", registrar):
            respuesta = self._descargar(formato="pdf", repartidor_id=self.repartidor.pk)
        self.assertEqual(respuesta.status_code, 200)
        for textos in paginas.values():
            if "Servicios" in textos:
                self.assertIn(f"Solicitud {solicitud.numero}", textos)

    def test_excel_no_recorre_la_hoja_completa_por_cada_fila(self):
        self._solicitud()
        datos_reporte = construir_reporte_motoristas(self.administrador, {
            "fecha_desde": self.fecha, "repartidor_id": self.repartidor.pk,
        }, ahora=self.ahora)
        motorista = datos_reporte["motoristas"][0]
        motorista["servicios"] = [{**motorista["servicios"][0], "numero": f"PRUEBA-{n}"} for n in range(200)]
        llamadas = []
        obtener_maximo = Worksheet.max_column.fget

        def contar(hoja):
            llamadas.append(1)
            return obtener_maximo(hoja)

        with patch.object(Worksheet, "max_column", property(contar)):
            contenido, _ = exportar_excel(datos_reporte)
        self.assertLess(len(llamadas), 30)
        hoja = load_workbook(BytesIO(contenido))["Servicios"]
        self.assertEqual(hoja.max_row, 205)
        self.assertEqual(hoja["E205"].value, "PRUEBA-199")

    def test_cache_de_altura_respeta_el_ancho_de_cada_columna(self):
        self._solicitud()
        datos_reporte = construir_reporte_motoristas(self.administrador, {
            "fecha_desde": self.fecha, "repartidor_id": self.repartidor.pk,
        }, ahora=self.ahora)
        texto = "Nombre y destino extensos para comprobar ajuste " * 5
        motorista = datos_reporte["motoristas"][0]
        motorista["nombre"] = texto
        motorista["servicios"][0]["destino"] = texto
        contenido, _ = exportar_excel(datos_reporte)
        libro = load_workbook(BytesIO(contenido))
        self.assertGreater(libro["Servicios"].row_dimensions[6].height, libro["Resumen"].row_dimensions[6].height)
        self.assertEqual(libro["Servicios"]["J6"].value, texto)

    def test_pdf_recalcula_lineas_al_cambiar_ancho_y_conserva_division(self):
        estilo = ParagraphStyle("Prueba", fontName="Helvetica", fontSize=10, leading=12)
        texto = "Texto largo para varias líneas y distintas páginas " * 15
        optimizado = _ParrafoReporte(texto, estilo)
        referencia = Paragraph(texto, estilo)
        for ancho in (300, 300, 150, 150, 0, 0, 0.0000000001, 0.0000000001, 300):
            self.assertEqual(optimizado.wrap(ancho, 1000), referencia.wrap(ancho, 1000))
        partes = optimizado.split(300, 48)
        originales = referencia.split(300, 48)
        self.assertEqual(len(partes), 2)
        for parte, original in zip(partes, originales):
            self.assertEqual(parte.wrap(300, 1000), original.wrap(300, 1000))

    def test_mas_detalles_no_generan_consultas_por_cada_servicio(self):
        self._solicitud()
        self._jornada()
        usuario = self._lector()
        filtros = {"fecha_desde": self.fecha, "repartidor_id": self.repartidor.pk}
        with CaptureQueriesContext(connection) as iniciales:
            construir_reporte_motoristas(usuario, filtros, ahora=self.ahora)
        for _ in range(20):
            self._solicitud()
        with CaptureQueriesContext(connection) as ampliadas:
            reporte = construir_reporte_motoristas(usuario, filtros, ahora=self.ahora)
        self.assertEqual(len(ampliadas), len(iniciales))
        self.assertEqual(len(reporte["motoristas"][0]["servicios"]), 21)
