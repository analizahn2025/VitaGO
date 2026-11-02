"""Persistencia binaria, meses naturales y conservación de la trazabilidad."""

import base64
import tempfile
from datetime import datetime
from io import StringIO
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from django.core.files.storage import default_storage
from django.core.management import call_command, CommandError
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from apps.evidencias.imagenes import corte_retencion, inicio_mes
from apps.evidencias.mantenimiento import mantener_imagenes, RecuperadorImagenes
from apps.evidencias.models import EvidenciaSolicitud
from apps.evidencias.serializadores import SerializadorEvidenciaSolicitud
from apps.evidencias.tests import test_operacion as datos
from apps.incidencias.models import EvidenciaIncidencia, Incidencia
from apps.nucleo.tests.imagenes import crear_imagen_prueba
from apps.solicitudes.models import Solicitud


@override_settings(TIME_ZONE="America/Tegucigalpa", MODO_APLICACION="CORPORATIVO")
class PruebasImagenesBase64Retencion(TestCase):
    setUpTestData = classmethod(datos.PruebasOperacionConEvidencias.setUpTestData.__func__)

    def setUp(self):
        self.ahora = datetime(2026, 11, 1, tzinfo=ZoneInfo("America/Tegucigalpa"))
        self.enterContext(patch("django.utils.timezone.now", return_value=self.ahora))
        datos.PruebasOperacionConEvidencias.setUp(self)
        self.temporal = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(override_settings(MEDIA_ROOT=self.temporal))
        self.png = crear_imagen_prueba().read()
        self.cliente = APIClient()
        self.cliente.force_authenticate(self.administrador)

    def _foto(self, mes=10, *, anio=2026, modelo=EvidenciaSolicitud, legado=False):
        comun = {
            "repartidor": self.repartidor, "clave_almacenamiento": f"anterior/{uuid4()}.png" if legado else f"bd/{uuid4()}.png",
            "tipo_contenido": "image/png", "tamano_bytes": len(self.png),
            "latitud": "14.075000", "longitud": "-87.190000",
            "capturada_en": datetime(anio, mes, 1, tzinfo=ZoneInfo("America/Tegucigalpa")),
        }
        if not legado:
            comun.update(contenido_base64=base64.b64encode(self.png).decode("ascii"),
                         imagen_guardada_en=self.ahora, archivo_original_eliminado_en=self.ahora)
        if modelo is EvidenciaSolicitud:
            comun.update(solicitud=self.solicitud, tipo="FOTO_ENTREGA")
        else:
            comun["incidencia"] = Incidencia.objects.create(
                jornada=self.jornada, repartidor=self.repartidor, descripcion="Incidencia de prueba",
                latitud="14.075000", longitud="-87.190000", reportada_en=self.ahora,
            )
        return modelo.objects.create(**comun)

    def _mantener(self, **opciones):
        with self.captureOnCommitCallbacks(execute=True):
            resultado = mantener_imagenes(ahora=self.ahora, **opciones)
        return resultado

    def test_noviembre_borra_septiembre_y_anteriores(self):
        antiguas = [self._foto(mes) for mes in (1, 8, 9)]
        recientes = [self._foto(mes) for mes in (10, 11)]
        self.assertEqual(self._mantener()["imagenes_vencidas"], 3)
        for foto in antiguas:
            foto.refresh_from_db()
            self.assertIsNone(foto.contenido_base64)
            self.assertEqual(foto.imagen_eliminada_en, self.ahora)
        for foto in recientes:
            foto.refresh_from_db()
            self.assertEqual(base64.b64decode(foto.contenido_base64), self.png)
            self.assertIsNone(foto.imagen_eliminada_en)

    def test_diciembre_borra_octubre_pero_conserva_noviembre(self):
        octubre, noviembre = self._foto(10), self._foto(11)
        self.ahora = datetime(2026, 12, 1, tzinfo=ZoneInfo("America/Tegucigalpa"))
        self._mantener()
        octubre.refresh_from_db(); noviembre.refresh_from_db()
        self.assertIsNotNone(octubre.imagen_eliminada_en)
        self.assertIsNone(noviembre.imagen_eliminada_en)

    def test_corte_de_enero_y_anio_bisiesto(self):
        for fecha, esperado in ((datetime(2027, 1, 1), datetime(2026, 12, 1)),
                                (datetime(2028, 3, 1), datetime(2028, 2, 1))):
            self.assertEqual(corte_retencion(fecha.replace(tzinfo=ZoneInfo("America/Tegucigalpa"))),
                             esperado.replace(tzinfo=ZoneInfo("America/Tegucigalpa")))

    def test_no_cambia_de_mes_por_medianoche_utc(self):
        utc = ZoneInfo("UTC")
        self.assertEqual(corte_retencion(datetime(2026, 11, 1, 5, 59, tzinfo=utc)).month, 9)
        self.assertEqual(corte_retencion(datetime(2026, 11, 1, 6, 0, tzinfo=utc)).month, 10)

    def test_foto_del_limite_se_conserva(self):
        foto = self._foto(10)
        self._mantener()
        foto.refresh_from_db()
        self.assertIsNone(foto.imagen_eliminada_en)

    def test_retencion_incluye_fotos_de_incidencias(self):
        foto = self._foto(9, modelo=EvidenciaIncidencia)
        self._mantener(); foto.refresh_from_db()
        self.assertIsNone(foto.contenido_base64)
        self.assertIsNotNone(foto.imagen_eliminada_en)
        self.assertTrue(Incidencia.objects.filter(pk=foto.incidencia_id).exists())

    def test_retraso_de_varios_meses_se_recupera(self):
        foto = self._foto(9)
        self.ahora = datetime(2027, 3, 15, tzinfo=ZoneInfo("America/Tegucigalpa"))
        self._mantener(); foto.refresh_from_db()
        self.assertIsNone(foto.contenido_base64)

    def test_limpieza_idempotente_preserva_solicitud_y_datos_evidencia(self):
        foto = self._foto(9)
        anteriores = (foto.pk, foto.tipo, foto.capturada_en, foto.tamano_bytes, foto.solicitud_id)
        self._mantener()
        segunda = self._mantener(); foto.refresh_from_db()
        self.assertEqual(segunda["imagenes_vencidas"], 0)
        self.assertEqual(anteriores, (foto.pk, foto.tipo, foto.capturada_en, foto.tamano_bytes, foto.solicitud_id))
        self.assertEqual(Solicitud.objects.count(), 1)

    def test_simulacion_no_modifica_datos_ni_archivos(self):
        foto = self._foto(9)
        with patch.object(default_storage, "delete", side_effect=AssertionError("Sin borrado")):
            resultado = self._mantener(simular=True)
        foto.refresh_from_db()
        self.assertEqual(resultado["imagenes_vencidas"], 1)
        self.assertIsNone(foto.imagen_eliminada_en)
        self.assertIsNotNone(foto.contenido_base64)

    def test_descarga_decodifica_bytes_exactos_con_permisos(self):
        foto = self._foto()
        respuesta = self.cliente.get(reverse("solicitudes:evidencias:archivo", kwargs={"solicitud_id": self.solicitud.pk, "evidencia_id": foto.pk}))
        self.assertEqual(respuesta.status_code, 200, getattr(respuesta, "data", None))
        self.assertEqual(b"".join(respuesta.streaming_content), self.png)
        self.assertEqual(respuesta["Content-Type"], "image/png")
        self.assertEqual(respuesta["Cache-Control"], "private, no-store")

    def test_imagen_vencida_devuelve_410_aunque_no_corrio_tarea(self):
        foto = self._foto(9)
        respuesta = self.cliente.get(reverse("solicitudes:evidencias:archivo", kwargs={"solicitud_id": self.solicitud.pk, "evidencia_id": foto.pk}))
        self.assertEqual(respuesta.status_code, 410)
        self.assertIn("retención", str(respuesta.data["detail"]))
        self.assertFalse(SerializadorEvidenciaSolicitud(foto).data["archivo_disponible"])

    def test_sin_autenticacion_no_expone_contenido_ni_fecha(self):
        foto = self._foto()
        self.cliente.force_authenticate(None)
        respuesta = self.cliente.get(reverse("solicitudes:evidencias:archivo", kwargs={"solicitud_id": self.solicitud.pk, "evidencia_id": foto.pk}))
        self.assertEqual(respuesta.status_code, 401)

    def test_una_imagen_vencida_no_omite_el_control_de_permisos(self):
        from apps.usuarios.models import Usuario
        foto = self._foto(9)
        ajeno = Usuario.objetos.create(correo="ajeno@imagenes.test", nombres="Ajeno", apellidos="Prueba")
        self.cliente.force_authenticate(ajeno)
        respuesta = self.cliente.get(reverse("solicitudes:evidencias:archivo", kwargs={"solicitud_id": self.solicitud.pk, "evidencia_id": foto.pk}))
        self.assertIn(respuesta.status_code, (403, 404))

    def test_base64_corrupto_no_expone_excepcion_interna(self):
        foto = self._foto()
        EvidenciaSolicitud.objects.filter(pk=foto.pk).update(contenido_base64="!" * len(foto.contenido_base64))
        respuesta = self.cliente.get(reverse("solicitudes:evidencias:archivo", kwargs={"solicitud_id": self.solicitud.pk, "evidencia_id": foto.pk}))
        self.assertEqual(respuesta.status_code, 404)

    def test_incidencia_vencida_devuelve_410(self):
        foto = self._foto(9, modelo=EvidenciaIncidencia)
        respuesta = self.cliente.get(reverse("incidencias:archivo-evidencia", kwargs={"incidencia_id": foto.incidencia_id, "evidencia_id": foto.pk}))
        self.assertEqual(respuesta.status_code, 410)

    def test_metadatos_incluyen_expiracion_sin_base64(self):
        foto = self._foto(10)
        salida = SerializadorEvidenciaSolicitud(foto).data
        self.assertEqual(salida["imagen_expira_en"], "2026-12-01T00:00:00-06:00")
        self.assertNotIn("contenido_base64", salida)
        self.assertNotIn("clave_almacenamiento", salida)

    def test_manager_no_carga_fotos_en_listados_ni_hace_n_mas_uno(self):
        for _ in range(5):
            self._foto()
        with CaptureQueriesContext(connection) as consultas:
            fotos = list(EvidenciaSolicitud.objects.all())
            SerializadorEvidenciaSolicitud(fotos, many=True).data
        self.assertTrue(all("contenido_base64" in f.get_deferred_fields() for f in fotos))
        self.assertNotIn('"contenido_base64"', consultas[0]["sql"])
        # solicitud es una relación del contrato; comprobar aparte la disponibilidad.
        with CaptureQueriesContext(connection) as disponibilidad:
            self.assertTrue(all(f.archivo_disponible for f in fotos))
        self.assertEqual(len(disponibilidad), 0)

    def test_importa_original_sin_cambiar_bytes_y_lo_retira_tras_commit(self):
        foto = self._foto(10, legado=True)
        default_storage.save(foto.clave_almacenamiento, crear_imagen_prueba())
        with self.captureOnCommitCallbacks(execute=True):
            resultado = mantener_imagenes(ahora=self.ahora)
            self.assertTrue(default_storage.exists(foto.clave_almacenamiento))
        foto.refresh_from_db()
        self.assertEqual(resultado["imagenes_migradas"], 1)
        self.assertEqual(base64.b64decode(foto.contenido_base64), self.png)
        self.assertFalse(default_storage.exists(foto.clave_almacenamiento))
        self.assertIsNotNone(foto.archivo_original_eliminado_en)

    def test_original_ausente_no_se_inventa_ni_se_borra_registro(self):
        foto = self._foto(10, legado=True)
        self.assertEqual(self._mantener()["originales_no_disponibles"], 1)
        foto.refresh_from_db()
        self.assertIsNone(foto.imagen_guardada_en)
        self.assertIsNone(foto.contenido_base64)
        self.assertFalse(foto.archivo_disponible)

    def test_importacion_puede_conservar_original_para_verificar_otros_destinos(self):
        foto = self._foto(10, legado=True)
        default_storage.save(foto.clave_almacenamiento, crear_imagen_prueba())
        self._mantener(retirar_originales=False)
        foto.refresh_from_db()
        self.assertEqual(base64.b64decode(foto.contenido_base64), self.png)
        self.assertTrue(default_storage.exists(foto.clave_almacenamiento))
        self.assertIsNone(foto.archivo_original_eliminado_en)

    def test_original_corrupto_se_conserva_y_no_se_importa(self):
        foto = self._foto(10, legado=True)
        from django.core.files.base import ContentFile
        default_storage.save(foto.clave_almacenamiento, ContentFile(b"x" * len(self.png)))
        self.assertEqual(self._mantener()["errores"], 1)
        self.assertTrue(default_storage.exists(foto.clave_almacenamiento))
        foto.refresh_from_db(); self.assertIsNone(foto.imagen_guardada_en)

    def test_retencion_elimina_tambien_original_anterior_sin_importarlo(self):
        foto = self._foto(9, legado=True)
        default_storage.save(foto.clave_almacenamiento, crear_imagen_prueba())
        resultado = self._mantener()
        foto.refresh_from_db()
        self.assertEqual(resultado["imagenes_migradas"], 0)
        self.assertFalse(default_storage.exists(foto.clave_almacenamiento))
        self.assertIsNotNone(foto.imagen_eliminada_en)

    def test_fallo_al_retirar_original_no_pierde_copia_bd_y_reintenta(self):
        foto = self._foto(10, legado=True)
        default_storage.save(foto.clave_almacenamiento, crear_imagen_prueba())
        with patch.object(default_storage, "delete", side_effect=OSError("Fallo sintético")):
            resultado = self._mantener()
        self.assertTrue(resultado["pendiente"])
        foto.refresh_from_db()
        self.assertEqual(base64.b64decode(foto.contenido_base64), self.png)
        self.assertIsNone(foto.archivo_original_eliminado_en)
        self._mantener(); foto.refresh_from_db()
        self.assertIsNotNone(foto.archivo_original_eliminado_en)

    def test_importacion_de_incidencias_tambien_es_base64(self):
        foto = self._foto(10, modelo=EvidenciaIncidencia, legado=True)
        default_storage.save(foto.clave_almacenamiento, crear_imagen_prueba())
        self._mantener(); foto.refresh_from_db()
        self.assertEqual(base64.b64decode(foto.contenido_base64), self.png)

    def test_limite_de_tiempo_deja_pendientes_para_reintento(self):
        foto = self._foto(9)
        resultado = self._mantener(limite_segundos=0)
        self.assertTrue(resultado["pendiente"])
        foto.refresh_from_db(); self.assertIsNone(foto.imagen_eliminada_en)

    def test_comando_rechaza_otro_despliegue(self):
        with self.assertRaises(CommandError):
            call_command("mantener_imagenes", modo_esperado="EXTERNO", simular=True, stdout=StringIO())

    def test_comando_simula_sin_borrar_y_confirma(self):
        foto = self._foto(9)
        call_command("mantener_imagenes", modo_esperado="CORPORATIVO", simular=True, stdout=StringIO())
        foto.refresh_from_db(); self.assertIsNone(foto.imagen_eliminada_en)
        call_command("mantener_imagenes", modo_esperado="CORPORATIVO", confirmar=True, stdout=StringIO())
        foto.refresh_from_db(); self.assertIsNotNone(foto.imagen_eliminada_en)

    @override_settings(HABILITAR_MANTENIMIENTO_IMAGENES=True)
    def test_recuperador_no_repite_y_cruza_mes_automaticamente(self):
        recuperador = RecuperadorImagenes()
        with patch("apps.evidencias.mantenimiento.mantener_imagenes", return_value={"pendiente": False, "imagenes_vencidas": 0, "imagenes_migradas": 0}) as mantener:
            recuperador.recuperar(); recuperador.recuperar()
            self.assertEqual(mantener.call_count, 1)
            self.assertLessEqual(recuperador._siguiente, inicio_mes(self.ahora, 1))
            with patch("django.utils.timezone.now", return_value=inicio_mes(self.ahora, 1)):
                recuperador.recuperar()
            self.assertEqual(mantener.call_count, 2)

    @override_settings(HABILITAR_MANTENIMIENTO_IMAGENES=True)
    def test_error_de_limpieza_no_rompe_api_y_programa_reintento(self):
        recuperador = RecuperadorImagenes()
        with patch("apps.evidencias.mantenimiento.mantener_imagenes", side_effect=RuntimeError("Fallo sintético")):
            recuperador.recuperar()
        self.assertEqual((recuperador._siguiente - self.ahora).total_seconds(), 300)

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_aplica_la_misma_retencion(self):
        foto = self._foto(9)
        self._mantener(); foto.refresh_from_db()
        self.assertIsNotNone(foto.imagen_eliminada_en)


class PruebasPlanificadorImagenes(TestCase):
    @override_settings(HABILITAR_MANTENIMIENTO_IMAGENES=True)
    def test_arranque_una_sola_vez_por_proceso(self):
        from apps.evidencias import planificador
        with patch.object(planificador, "_hilo", None), patch.object(planificador, "_proceso", None), \
                patch.object(planificador.threading, "Thread") as hilo:
            hilo.return_value.is_alive.return_value = True
            planificador.iniciar_planificador_imagenes()
            planificador.iniciar_planificador_imagenes()
            hilo.assert_called_once()
            self.assertTrue(hilo.call_args.kwargs["daemon"])
            hilo.return_value.start.assert_called_once()

    @override_settings(HABILITAR_MANTENIMIENTO_IMAGENES=False)
    def test_comandos_y_pruebas_no_inician_hilos(self):
        from apps.evidencias import planificador
        with patch.object(planificador.threading, "Thread") as hilo:
            planificador.iniciar_planificador_imagenes()
            hilo.assert_not_called()

    def test_timer_ejecuta_sin_peticiones_y_cierra_conexion_propia(self):
        from apps.evidencias import planificador
        from unittest.mock import Mock
        detener = Mock()
        detener.wait.side_effect = [False, False, True]
        with patch("apps.evidencias.mantenimiento.recuperar_imagenes") as recuperar, \
                patch.object(planificador.connections, "close_all") as cerrar:
            planificador._ejecutar(detener)
            self.assertEqual(recuperar.call_count, 2)
            self.assertEqual(cerrar.call_count, 2)
        detener.wait.assert_called_with(60)

    def test_error_del_timer_no_cancela_la_siguiente_revision(self):
        from apps.evidencias import planificador
        from unittest.mock import Mock
        detener = Mock(); detener.wait.side_effect = [False, False, True]
        with patch("apps.evidencias.mantenimiento.recuperar_imagenes", side_effect=[RuntimeError("Sintético"), None]) as recuperar, \
                patch.object(planificador.connections, "close_all"):
            planificador._ejecutar(detener)
            self.assertEqual(recuperar.call_count, 2)

    def test_gunicorn_difiere_arranque_hasta_worker(self):
        from apps.evidencias import planificador
        with patch.dict("sys.modules", {"gunicorn": object()}), \
                patch.object(planificador, "iniciar_planificador_imagenes") as iniciar:
            planificador.iniciar_planificador_servidor()
            iniciar.assert_not_called()

    def test_hook_gunicorn_inicia_temporizador_en_worker(self):
        import runpy
        from pathlib import Path
        configuracion = runpy.run_path(str(Path(__file__).resolve().parents[3] / "gunicorn.conf.py"))
        with patch("apps.evidencias.planificador.iniciar_planificador_imagenes") as iniciar:
            configuracion["post_worker_init"](object())
            iniciar.assert_called_once()
