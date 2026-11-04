from datetime import date, timedelta
from io import BytesIO
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

from apps.organizaciones.models import Empresa, Sucursal
from apps.reportes.exportadores import exportar_excel, _ParrafoReporte
from apps.reportes.fuentes import _FuenteUnicode, texto_pdf
from apps.reportes.selectores import construir_reporte_motoristas, construir_reporte_servicios
from apps.reportes.serializadores import SerializadorConsultaReporteMotoristas
from apps.repartidores.tests import test_resumenes as datos
from apps.solicitudes.models import AsignacionSolicitud, Solicitud


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasReportesMotoristas(TestCase):
    setUpTestData = classmethod(datos.PruebasResumenesMotoristas.setUpTestData.__func__)
    setUp = datos.PruebasResumenesMotoristas.setUp
    _solicitud = datos.PruebasResumenesMotoristas._solicitud
    _jornada = datos.PruebasResumenesMotoristas._jornada
    _lector = datos.PruebasResumenesMotoristas._lector
    _lectura = datos.PruebasResumenesMotoristas._lectura

    def _descargar(self, *, servicios=False, **opciones):
        ruta = "servicios" if servicios else "motoristas"
        parametros = {"fecha": str(self.fecha)} if servicios else {"periodo": "MENSUAL", "mes": "2026-10"}
        return self.cliente.get(reverse(f"reportes:{ruta}-descargar"), {**parametros, **opciones})

    def _filtros(self, **opciones):
        entrada = SerializadorConsultaReporteMotoristas(data={"periodo": "MENSUAL", "mes": "2026-10", **opciones})
        entrada.is_valid(raise_exception=True)
        return entrada.validated_data

    def _resumen(self, **opciones):
        return construir_reporte_motoristas(self.administrador, self._filtros(repartidor_id=self.repartidor.pk, **opciones), ahora=self.ahora)

    def _hoja(self, *, servicios=False, **opciones):
        r = self._descargar(servicios=servicios, repartidor_id=self.repartidor.pk, **opciones)
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        return load_workbook(BytesIO(r.content), data_only=False).active

    def test_resumen_una_tabla_una_fila_por_motorista_sin_duplicar_km(self):
        self._solicitud(); self._solicitud(); self._solicitud(estado="DELIVERY_FAILED"); self._solicitud(estado="CANCELLED")
        self._jornada("8.250"); self._lectura("4.50", solicitud=Solicitud.objects.first())
        r = self._descargar(repartidor_id=self.repartidor.pk)
        self.assertEqual(r.status_code, 200)
        self.assertIn("vitago-motoristas-mensual-2026-10.xlsx", r["Content-Disposition"])
        self.assertIn("no-store", r["Cache-Control"])
        libro = load_workbook(BytesIO(r.content))
        self.assertEqual(libro.sheetnames, ["Resumen"])
        hoja = libro.active
        valores = dict(zip([c.value for c in hoja[6]], [c.value for c in hoja[7]]))
        self.assertEqual(hoja.max_column, 9)
        self.assertEqual(hoja.max_row, 7)
        for campo, valor in {"Completados": 2, "Fallidos": 1, "Cancelados": 1, "Jornadas": 1,
                             "Km GPS": 8.250, "Temp. promedio °C": 4.50}.items():
            self.assertEqual(valores[campo], valor, campo)
        self.assertEqual(hoja.freeze_panes, "D7")
        self.assertEqual(hoja["I7"].number_format, "0.00")
        self.assertFalse(any(c.data_type == "f" for fila in hoja for c in fila))

    def test_mensual_y_quincenas_del_calendario_incluyen_febrero_bisiesto(self):
        casos = [({}, date(2026,10,1), date(2026,10,31)),
                 ({"periodo":"QUINCENAL", "quincena":"1"}, date(2026,10,1), date(2026,10,15)),
                 ({"periodo":"QUINCENAL", "quincena":"2"}, date(2026,10,16), date(2026,10,31)),
                 ({"periodo":"QUINCENAL", "quincena":"2", "mes":"2024-02"}, date(2024,2,16), date(2024,2,29)),
                 ({"mes":"2026-02"}, date(2026,2,1), date(2026,2,28))]
        for opciones, inicio, fin in casos:
            with self.subTest(opciones=opciones):
                filtros = self._filtros(**opciones)
                self.assertEqual((filtros["fecha_desde"], filtros["fecha_hasta"]), (inicio, fin))

    def test_filtros_obligatorios_y_rechazo_de_fechas_diarias_en_resumen(self):
        url = reverse("reportes:motoristas-descargar")
        self.assertEqual(set(self.cliente.get(url).data), {"periodo", "mes"})
        for opciones, campo in [({"periodo":"DIARIO"},"periodo"), ({"mes":"2026-13"},"mes"),
            ({"mes":"0000-01"},"mes"), ({"mes":"2026-1"},"mes"), ({"mes":"2026-10\n"},"mes"),
            ({"mes":"9999-12"},"mes"), ({"quincena":"1"},"quincena"),
            ({"periodo":"QUINCENAL"},"quincena"), ({"periodo":"QUINCENAL", "quincena":"3"},"quincena"),
            ({"fecha_desde":"2026-10-01"},"fecha_desde"), ({"fecha_hasta":"2026-10-31"},"fecha_hasta"),
            ({"formato":"csv"},"formato"), ({"otro":"valor"},"otro")]:
            with self.subTest(opciones=opciones):
                r = self._descargar(**opciones)
                self.assertEqual(r.status_code, 400)
                self.assertIn(campo, r.data)

    def test_quincenas_no_mezclan_entregas_en_limites_de_honduras(self):
        for dia in (15,16,31):
            s = self._solicitud(historial=False)
            instante = self.inicio.replace(day=dia, hour=23, minute=59)
            Solicitud.objects.filter(pk=s.pk).update(entregada_en=instante)
        s = self._solicitud(historial=False)
        Solicitud.objects.filter(pk=s.pk).update(entregada_en=self.inicio.replace(month=11,day=1))
        a = self._resumen(periodo="QUINCENAL", quincena="1")
        b = self._resumen(periodo="QUINCENAL", quincena="2")
        self.assertEqual(a["motoristas"][0]["resumen"]["solicitudes"]["entregadas"], 1)
        self.assertEqual(b["motoristas"][0]["resumen"]["solicitudes"]["entregadas"], 2)

    def test_promedio_de_todas_las_lecturas_no_promedio_de_promedios_diarios(self):
        self._lectura("0.00"); self._lectura("6.00"); self._lectura(None)
        self._lectura("9.00", capturada=self.inicio + timedelta(days=1, hours=2))
        self._lectura("99.00", capturada=self.inicio.replace(month=11, day=1))
        hoja = self._hoja()
        self.assertEqual(hoja["I7"].value, 5)
        self.assertEqual(hoja["I7"].data_type, "n")
        self.assertEqual(self._resumen()["motoristas"][0]["resumen"]["temperaturas"]["ultimas_lecturas"], [])

    def test_cero_real_y_medicion_ausente_no_se_confunden(self):
        self.assertEqual((self._hoja()["H7"].value, self._hoja()["I7"].value), ("N/D", "N/D"))
        self._jornada("0.000"); self._lectura("0.00")
        hoja = self._hoja()
        self.assertEqual((hoja["H7"].value, hoja["I7"].value), (0, 0))

    def test_varias_jornadas_y_km_parciales_quedan_identificados(self):
        self._jornada("2.500"); self._jornada("4.000", finalizada=self.inicio + timedelta(days=1, hours=4))
        self._jornada(disponible=False, calidad="SIN_VERIFICAR")
        hoja = self._hoja()
        self.assertEqual((hoja["D7"].value, hoja["H7"].value), (3, 6.5))
        self.assertIn("*", hoja["H7"].number_format)

    def test_pdf_de_ambos_reportes_valido(self):
        self._solicitud(); self._jornada()
        for servicios in (False, True):
            r = self._descargar(servicios=servicios, formato="pdf", repartidor_id=self.repartidor.pk)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r["Content-Type"], "application/pdf")
            self.assertTrue(r.content.startswith(b"%PDF-"))
            self.assertIn(b"%%EOF", r.content)

    def test_servicios_se_descargan_aparte_con_fechas_tipadas_y_sin_km(self):
        solicitud = self._solicitud()
        hoja = self._hoja(servicios=True)
        self.assertEqual(hoja.title, "Servicios")
        self.assertEqual(hoja["C7"].value, solicitud.numero)
        self.assertEqual(hoja["G7"].value.hour, 1)
        self.assertIsNone(hoja["G7"].value.tzinfo)
        self.assertNotIn("Km GPS", [c.value for c in hoja[6]])
        self.assertEqual(hoja["I7"].value, 3)

    def test_servicios_diarios_requieren_fecha_exacta(self):
        url = reverse("reportes:servicios-descargar")
        self.assertEqual(self.cliente.get(url).status_code, 400)
        for fecha in ("2026-2-1", "2026-02-30", "9999-12-31"):
            r = self._descargar(servicios=True, fecha=fecha)
            self.assertEqual(r.status_code, 400)
            self.assertIn("fecha", r.data)
        self.assertEqual(self._descargar(servicios=True, mes="2026-10").status_code, 400)

    def test_servicios_vigentes_y_reasignados_se_ordenan_sin_mezclar_motoristas(self):
        s = self._solicitud()
        cambio = self.inicio + timedelta(hours=2, minutes=30)
        s.asignaciones.update(estado="REASIGNADA", finalizada_en=cambio)
        otro = self.repartidores[1]
        AsignacionSolicitud.objects.create(solicitud=s, repartidor=otro, asignada_por=self.administrador,
            asignada_en=cambio, finalizada_en=s.entregada_en, estado="FINALIZADA")
        reporte = construir_reporte_servicios(self.administrador, {"fecha":self.fecha}, ahora=self.ahora)
        tramos = [m["servicios"] for m in reporte["motoristas"] if m["servicios"]]
        self.assertEqual(len(tramos), 2)
        self.assertEqual([t[0]["numero"] for t in tramos], [s.numero, s.numero])
        self.assertNotEqual(tramos[0][0]["estado_asignacion"], tramos[1][0]["estado_asignacion"])

    def test_servicios_respeta_medianoche_y_asignaciones_de_otro_dia(self):
        incluidos = self._solicitud(estado="ASSIGNED")
        incluidos.asignaciones.update(asignada_en=self.inicio-timedelta(hours=2))
        fuera = self._solicitud()
        fuera.asignaciones.update(asignada_en=self.fin, finalizada_en=self.fin+timedelta(hours=3))
        antiguo = self._solicitud()
        antiguo.asignaciones.update(asignada_en=self.inicio-timedelta(days=2), finalizada_en=self.inicio)
        servicios = construir_reporte_servicios(self.administrador, {"fecha":self.fecha, "repartidor_id":self.repartidor.pk})
        self.assertEqual([s["numero"] for s in servicios["motoristas"][0]["servicios"]], [incluidos.numero])

    def test_topes_no_truncan_silenciosamente(self):
        self._solicitud(); self._solicitud()
        with patch("apps.reportes.selectores.LIMITE_FILAS", 1):
            r = self._descargar(servicios=True)
            self.assertEqual(r.status_code, 400)
            self.assertIn("fecha", r.data)
        with patch("apps.reportes.selectores.LIMITE_MOTORISTAS", 0):
            for servicios in (False, True):
                r = self._descargar(servicios=servicios)
                self.assertEqual(r.status_code, 400)
                self.assertIn("repartidor_id", r.data)

    def test_cinco_permisos_requeridos_y_autenticacion_en_ambos_reportes(self):
        codigos = ("reporte.ver", "repartidor.ver", "solicitud.ver", "jornada.ver", "evidencia.ver")
        for omitir in codigos:
            self.cliente.force_authenticate(self._lector(permisos=[c for c in codigos if c != omitir]))
            for servicios in (False, True):
                self.assertEqual(self._descargar(servicios=servicios).status_code, 403)
        self.cliente.force_authenticate(None)
        for servicios in (False, True):
            self.assertEqual(self._descargar(servicios=servicios).status_code, 401)

    def test_lector_de_sucursal_y_otra_empresa_no_exportan_historial_ajeno(self):
        self._solicitud()
        sucursal = Sucursal.objects.create(empresa=self.empresa, ubicacion=self.origen, nombre="Sucursal de prueba", codigo="REPORTE")
        otra = Empresa.objects.create(nombre="Otra empresa", pais=self.pais)
        for usuario in (self._lector(sucursal=sucursal), self._lector(empresa=otra)):
            self.cliente.force_authenticate(usuario)
            for servicios in (False, True):
                r = self._descargar(servicios=servicios, empresa_id=self.empresa.pk)
                self.assertEqual(r.status_code, 200)
                self.assertIn("Sin resultados", load_workbook(BytesIO(r.content)).active["A7"].value)

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_admin_exporta_flota_compartida_y_cliente_no_accede(self):
        from apps.repartidores.models import Repartidor
        from apps.usuarios.models import Usuario
        Repartidor.objects.filter(pk=self.repartidor.pk).update(empresa=None)
        Usuario.objetos.filter(pk=self.repartidor.usuario_id).update(empresa=None)
        self.assertEqual(self._hoja()["B7"].value, "Network - flota compartida")
        self.cliente.force_authenticate(self._lector())
        for servicios in (False, True):
            r = self._descargar(servicios=servicios, repartidor_id=self.repartidor.pk)
            self.assertIn("Sin resultados", load_workbook(BytesIO(r.content)).active["A7"].value)

    def test_accept_binario_conserva_errores_json(self):
        url = reverse("reportes:motoristas-descargar")
        r = self.cliente.get(url, {"periodo":"MENSUAL", "mes":"2026-10", "formato":"pdf"}, HTTP_ACCEPT="application/pdf")
        self.assertEqual(r.status_code, 200)
        error = self.cliente.get(url, {"formato":"invalido"}, HTTP_ACCEPT="application/pdf")
        self.assertEqual(error.status_code, 400)
        self.assertIn("application/json", error["Content-Type"])

    def test_inyeccion_de_formulas_se_exporta_como_texto(self):
        self.repartidor.usuario.nombres = "=1+1"
        self.repartidor.usuario.save(update_fields=("nombres",))
        self._solicitud()
        for servicios in (False, True):
            celda = self._hoja(servicios=servicios)["A7"]
            self.assertTrue(celda.value.startswith("=1+1"))
            self.assertEqual(celda.data_type, "s")

    def test_nombre_largo_y_saltos_de_linea_no_se_truncan(self):
        usuario = self.repartidor.usuario
        usuario.nombres = "María Alejandra " * 6 + "\n".join(["Nombre"] * 6)
        usuario.apellidos = "Hernández Martínez " * 7
        usuario.save(update_fields=("nombres", "apellidos"))
        self._solicitud()
        for servicios in (False, True):
            hoja = self._hoja(servicios=servicios)
            self.assertEqual(hoja["A7"].value, f"{usuario.nombres} {usuario.apellidos}".strip())
            self.assertGreater(hoja.row_dimensions[7].height, 90)
            self.assertLessEqual(hoja.row_dimensions[7].height, 409.5)

    def _destino_especial(self, solicitud, texto):
        Solicitud.objects.filter(pk=solicitud.pk).update(modalidad="ESPECIAL", destino=None, destino_especial=texto)

    def test_excel_destino_extenso_ajusta_altura_y_rechaza_texto_imposible(self):
        s = self._solicitud()
        texto = "Detalle del destino especial de demostración " * 24
        self._destino_especial(s, texto)
        hoja = self._hoja(servicios=True)
        self.assertEqual(hoja["E7"].value, texto)
        self.assertGreater(hoja.row_dimensions[7].height, 28)
        self.assertLessEqual(hoja.row_dimensions[7].height, 409.5)
        for texto in ("x"*32768, "\n".join(["Texto"]*100)):
            self._destino_especial(s, texto)
            r = self._descargar(servicios=True)
            self.assertEqual(r.status_code, 400)
            self.assertIn("PDF", str(r.data["formato"]))

    def test_pdf_identifica_servicio_en_todas_sus_paginas(self):
        solicitud = self._solicitud()
        self._destino_especial(solicitud, "CONTENIDO DEL DESTINO ESPECIAL " * 400)
        paginas, dibujar = {}, Paragraph.draw
        def registrar(parrafo):
            paginas.setdefault(parrafo.canv.getPageNumber(), []).append(parrafo.getPlainText())
            return dibujar(parrafo)
        with patch.object(Paragraph, "draw", registrar):
            r = self._descargar(servicios=True, formato="pdf", repartidor_id=self.repartidor.pk)
        self.assertEqual(r.status_code, 200)
        continuaciones = [textos for textos in paginas.values() if any("CONTENIDO DEL DESTINO" in t for t in textos)]
        self.assertGreaterEqual(len(continuaciones), 2)
        for textos in continuaciones:
            self.assertIn(f"Solicitud {solicitud.numero}", textos)

    def test_pdf_unicode_y_glifo_no_disponible(self):
        usuario = self.repartidor.usuario
        usuario.nombres = "María 漢字 🚚"
        usuario.save(update_fields=("nombres",))
        mapas, agregar = [], _FuenteUnicode.addObjects
        def registrar(fuente, documento):
            agregar(fuente, documento)
            mapas.extend(o.content for n, o in documento.idToObject.items() if n.startswith("toUnicodeCMap:"))
        with patch.object(_FuenteUnicode, "addObjects", registrar):
            r = self._descargar(formato="pdf", repartidor_id=self.repartidor.pk)
        self.assertEqual(r.status_code, 200)
        for codigo in ("<6F22>", "<5B57>", "<D83DDE9A>"):
            self.assertIn(codigo, "\n".join(mapas))
        contenido = texto_pdf("Texto <b>literal</b> \u0378")
        self.assertIn("&lt;b&gt;literal&lt;/b&gt;", contenido)
        self.assertIn("[U+0378]", contenido)

    def test_excel_no_recorre_la_hoja_por_cada_fila_y_respeta_anchos(self):
        self._solicitud()
        reporte = construir_reporte_servicios(self.administrador, {"fecha":self.fecha, "repartidor_id":self.repartidor.pk})
        motorista = reporte["motoristas"][0]
        texto = "Nombre y destino extensos para comprobar ajuste " * 5
        motorista["nombre"] = texto
        motorista["servicios"] = [{**motorista["servicios"][0], "numero":f"PRUEBA-{n}", "destino":texto} for n in range(200)]
        llamadas, obtener = [], Worksheet.max_column.fget
        def contar(hoja):
            llamadas.append(1)
            return obtener(hoja)
        with patch.object(Worksheet, "max_column", property(contar)):
            contenido, _ = exportar_excel(reporte)
        self.assertLess(len(llamadas), 30)
        hoja = load_workbook(BytesIO(contenido)).active
        self.assertEqual(hoja.max_row, 206)
        self.assertEqual(hoja["C206"].value, "PRUEBA-199")
        self.assertEqual(hoja["E206"].value, texto)

    def test_pdf_recalcula_lineas_al_cambiar_ancho_y_conserva_division(self):
        estilo = ParagraphStyle("Prueba", fontName="Helvetica", fontSize=10, leading=12)
        texto = "Texto largo para varias líneas y distintas páginas " * 15
        optimizado, referencia = _ParrafoReporte(texto, estilo), Paragraph(texto, estilo)
        for ancho in (300,300,150,150,0,0,0.0000000001,0.0000000001,300):
            self.assertEqual(optimizado.wrap(ancho,1000), referencia.wrap(ancho,1000))
        partes, originales = optimizado.split(300,48), referencia.split(300,48)
        self.assertEqual(len(partes), 2)
        for parte, original in zip(partes, originales):
            self.assertEqual(parte.wrap(300,1000), original.wrap(300,1000))

    def test_consultas_constantes_y_resumen_no_carga_detalles_ni_imagenes(self):
        self._solicitud(); self._jornada(); self._lectura()
        usuario = self._lector()
        filtros = self._filtros(repartidor_id=self.repartidor.pk)
        for constructor, entrada in ((construir_reporte_motoristas, filtros),
                                     (construir_reporte_servicios, {"fecha":self.fecha, "repartidor_id":self.repartidor.pk})):
            with CaptureQueriesContext(connection) as iniciales:
                constructor(usuario, entrada, ahora=self.ahora)
            for _ in range(10):
                self._solicitud()
            with CaptureQueriesContext(connection) as ampliadas:
                reporte = constructor(usuario, entrada, ahora=self.ahora)
            self.assertEqual(len(ampliadas), len(iniciales))
            self.assertNotIn("imagen_base64", " ".join(q["sql"] for q in ampliadas).lower())
            if constructor == construir_reporte_motoristas:
                self.assertNotIn("servicios", reporte["motoristas"][0])
                self.assertNotIn("row_number", " ".join(q["sql"] for q in ampliadas).lower())
