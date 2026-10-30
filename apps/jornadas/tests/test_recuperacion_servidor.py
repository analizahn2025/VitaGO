"""Reinicio, despertar y cambio de fecha, sin bases ni proveedores externos."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import importlib
import threading
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from apps.jornadas import recuperacion
from apps.jornadas.models import AlmuerzoJornada, JornadaRepartidor
from apps.jornadas.servicios import iniciar_jornada
from apps.jornadas.tests import test_jornadas as datos
from apps.notificaciones.models import NotificacionUsuario
from apps.nucleo.middleware import MiddlewareRecuperacionCierre
from apps.solicitudes.contingencias import procesar_cierre_diario
from apps.solicitudes.models import AsignacionSolicitud, EventoSolicitud, Solicitud


@override_settings(HABILITAR_RECUPERACION_CIERRE=True, MODO_APLICACION="CORPORATIVO", TIME_ZONE="America/Tegucigalpa")
class PruebasRecuperacionServidor(TestCase):
    setUpTestData = classmethod(datos.PruebasJornadas.setUpTestData.__func__)

    def setUp(self):
        self.ahora = datetime(2026, 10, 30, 8, tzinfo=ZoneInfo("America/Tegucigalpa"))
        reloj = patch("django.utils.timezone.now", return_value=self.ahora)
        self.reloj = reloj.start()
        self.addCleanup(reloj.stop)
        self.recuperador = recuperacion.RecuperadorCierreOperativo()
        estado = patch.object(recuperacion, "_recuperador", self.recuperador)
        estado.start()
        self.addCleanup(estado.stop)
        self.repartidor = self.repartidores[0]

    def _jornada(self, dias=2):
        inicio = self.ahora.replace(hour=15) - timedelta(days=dias)
        return JornadaRepartidor.objects.create(repartidor=self.repartidor, iniciada_en=inicio)

    def _servicio(self, jornada, estado="IN_TRANSIT"):
        solicitud = Solicitud.objects.create(
            numero=f"REINICIO-{Solicitud.objects.count()}", empresa=self.empresa,
            solicitada_por=self.administrador, repartidor_asignado=self.repartidor,
            origen=self.origen, destino=self.destino, estado=estado, prioridad="NORMAL", cantidad_tubos=1,
            recolectada_en=jornada.iniciada_en + timedelta(minutes=2) if estado == "IN_TRANSIT" else None,
        )
        Solicitud.objects.filter(pk=solicitud.pk).update(creado_en=jornada.iniciada_en + timedelta(minutes=1))
        AsignacionSolicitud.objects.create(solicitud=solicitud, repartidor=self.repartidor,
            asignada_por=self.administrador, asignada_en=jornada.iniciada_en + timedelta(minutes=1))
        return solicitud

    def test_arranque_recupera_dias_atrasados_y_conserva_corte_22(self):
        jornada = self._jornada()
        solicitud = self._servicio(jornada)
        self.assertTrue(self.recuperador.recuperar(forzar=True))
        solicitud.refresh_from_db(); jornada.refresh_from_db()
        self.repartidor.refresh_from_db()
        corte = (self.ahora - timedelta(days=2)).replace(hour=22)
        self.assertEqual((solicitud.estado, solicitud.cerrada_en, solicitud.motivo_cierre), ("DELIVERY_FAILED", corte, "FIN_DIA"))
        self.assertEqual((jornada.estado, jornada.finalizada_en), ("FINALIZADA", corte))
        self.assertEqual(self.repartidor.estado_operativo, "OFFLINE")
        self.assertFalse(AsignacionSolicitud.objects.filter(estado="ACTIVA").exists())
        evento = EventoSolicitud.objects.get(tipo="CIERRE_AUTOMATICO")
        self.assertEqual(datetime.fromisoformat(evento.metadatos["ejecutado_en"]), self.ahora)

    def test_primera_consulta_muestra_cierre_recuperado(self):
        jornada = self._jornada()
        self._servicio(jornada)
        from rest_framework.test import APIClient
        cliente = APIClient()
        cliente.force_authenticate(self.repartidor.usuario)
        respuesta = cliente.get("/api/v1/jornadas/activa/")
        self.assertEqual(respuesta.status_code, 200)
        self.assertIsNone(respuesta.data["jornada"])
        self.assertFalse(respuesta.data["cierre_pendiente"])
        self.assertTrue(respuesta.data["puede_iniciar_jornada"])

    def test_reactivar_despues_de_varios_dias_no_reutiliza_comprobacion_antigua(self):
        self.assertTrue(self.recuperador.recuperar())
        self.reloj.return_value = self.ahora.replace(hour=16)
        jornada = self._jornada(dias=0)
        self.reloj.return_value = self.ahora + timedelta(days=3)
        self.assertTrue(self.recuperador.recuperar())
        jornada.refresh_from_db()
        self.assertEqual(jornada.finalizada_en, self.ahora.replace(hour=22))

    def test_peticiones_seguidas_reutilizan_revision_sin_consultas(self):
        self.assertTrue(self.recuperador.recuperar())
        with self.assertNumQueries(0):
            self.assertTrue(self.recuperador.recuperar())

    def test_revision_no_se_extiende_mas_alla_del_corte(self):
        inicio = self.ahora.replace(hour=21, minute=59, second=50)
        self.reloj.return_value = inicio
        jornada = self._jornada(dias=0)
        self.assertTrue(self.recuperador.recuperar())
        self.reloj.return_value = inicio.replace(hour=22, minute=0, second=0)
        self.assertTrue(self.recuperador.recuperar())
        jornada.refresh_from_db()
        self.assertEqual(jornada.estado, "FINALIZADA")

    def test_revision_que_cruza_22_no_habilita_operaciones_con_datos_previos(self):
        self.reloj.return_value = self.ahora.replace(hour=21, minute=59, second=59)
        jornada = self._jornada(dias=0)
        procesar = procesar_cierre_diario
        def cruzar_corte(*args, **kwargs):
            resultado = procesar(*args, **kwargs)
            self.reloj.return_value += timedelta(seconds=2)
            return resultado
        with patch.object(recuperacion, "procesar_cierre_diario", side_effect=cruzar_corte):
            self.assertFalse(self.recuperador.recuperar())
        self.reloj.return_value += timedelta(seconds=5)
        self.assertTrue(self.recuperador.recuperar())
        jornada.refresh_from_db()
        self.assertEqual(jornada.estado, "FINALIZADA")

    def test_repetir_arranque_no_duplica_eventos_avisos_o_jornadas(self):
        jornada = self._jornada()
        self._servicio(jornada)
        self.assertTrue(self.recuperador.recuperar(forzar=True))
        conteos = (EventoSolicitud.objects.count(), NotificacionUsuario.objects.count(), JornadaRepartidor.objects.count())
        self.assertTrue(recuperacion.RecuperadorCierreOperativo().recuperar(forzar=True))
        self.assertEqual(conteos, (EventoSolicitud.objects.count(), NotificacionUsuario.objects.count(), JornadaRepartidor.objects.count()))

    def test_jornada_y_servicio_vigentes_no_se_cierran(self):
        self.reloj.return_value = self.ahora.replace(hour=18)
        jornada = self._jornada(dias=0)
        solicitud = self._servicio(jornada)
        self.assertTrue(self.recuperador.recuperar())
        jornada.refresh_from_db(); solicitud.refresh_from_db()
        self.assertEqual((jornada.estado, solicitud.estado), ("ACTIVA", "IN_TRANSIT"))

    def test_almuerzo_atrasado_tambien_se_cierra_al_corte(self):
        jornada = self._jornada()
        almuerzo = AlmuerzoJornada.objects.create(jornada=jornada, iniciada_en=jornada.iniciada_en + timedelta(minutes=10))
        self.assertTrue(self.recuperador.recuperar())
        almuerzo.refresh_from_db(); jornada.refresh_from_db()
        self.assertEqual(almuerzo.finalizada_en, jornada.cierre_programado_en)

    def test_jornada_historica_sin_metadatos_tambien_se_recupera(self):
        jornada = self._jornada()
        JornadaRepartidor.objects.filter(pk=jornada.pk).update(fecha_operativa=None, cierre_programado_en=None)
        self.assertTrue(self.recuperador.recuperar())
        jornada.refresh_from_db()
        self.assertEqual(jornada.finalizada_en, (self.ahora - timedelta(days=2)).replace(hour=22))

    def test_corte_guardado_se_respeta_si_cambio_el_huso_de_la_empresa(self):
        self.reloj.return_value = self.ahora.replace(hour=18)
        jornada = self._jornada(dias=0)
        corte_anterior = self.ahora.replace(hour=16)
        JornadaRepartidor.objects.filter(pk=jornada.pk).update(cierre_programado_en=corte_anterior)
        self.assertTrue(self.recuperador.recuperar())
        jornada.refresh_from_db()
        self.assertEqual(jornada.finalizada_en, corte_anterior)

    def test_cache_respeta_corte_guardado_distinto_del_huso_actual(self):
        self.reloj.return_value = self.ahora.replace(hour=15, minute=59, second=50)
        jornada = self._jornada(dias=0)
        corte = self.ahora.replace(hour=16)
        JornadaRepartidor.objects.filter(pk=jornada.pk).update(cierre_programado_en=corte)
        self.assertTrue(self.recuperador.recuperar())
        self.reloj.return_value = corte
        self.assertTrue(self.recuperador.recuperar())
        jornada.refresh_from_db()
        self.assertEqual(jornada.finalizada_en, corte)

    def test_perfil_antiguo_sin_empresa_no_impide_cierre_global(self):
        jornada = self._jornada()
        self.repartidor.vehiculo.empresa = None
        self.repartidor.vehiculo.save()
        self.repartidor.empresa = None
        self.repartidor.save()
        self.assertTrue(self.recuperador.recuperar())
        jornada.refresh_from_db()
        self.assertEqual(jornada.estado, "FINALIZADA")

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_tambien_recupera_servicios_y_jornada(self):
        jornada = self._jornada()
        solicitud = self._servicio(jornada, estado="ASSIGNED")
        self.assertTrue(self.recuperador.recuperar())
        jornada.refresh_from_db(); solicitud.refresh_from_db()
        self.assertEqual((jornada.estado, solicitud.estado), ("FINALIZADA", "PICKUP_FAILED"))

    def test_revision_respeta_husos_corporativos_antes_del_corte(self):
        self.pais.zona_horaria_predeterminada = "UTC"
        self.pais.save()
        self.reloj.return_value = self.ahora.replace(hour=15, minute=59, second=50)  # 21:59:50 UTC
        jornada = self._jornada(dias=0)
        self.assertTrue(self.recuperador.recuperar())
        self.reloj.return_value = self.ahora.replace(hour=16)  # 22:00 UTC
        self.assertTrue(self.recuperador.recuperar())
        jornada.refresh_from_db()
        self.assertEqual(jornada.estado, "FINALIZADA")

    def test_fallo_transitorio_no_habilita_vista_y_se_reintenta(self):
        jornada = self._jornada()
        with patch.object(recuperacion, "procesar_cierre_diario", side_effect=RuntimeError("Fallo sintético")):
            with self.assertLogs("vitago.api", level="ERROR"):
                respuesta = self.client.get("/api/v1/salud/")
        self.assertEqual(respuesta.status_code, 503)
        self.assertEqual(respuesta.json()["codigo"], "CIERRE_OPERATIVO_PENDIENTE")
        self.assertEqual(respuesta["Retry-After"], "5")
        with patch.object(recuperacion, "procesar_cierre_diario") as procesar, self.assertNumQueries(0):
            self.assertEqual(self.client.get("/api/v1/salud/").status_code, 503)
        procesar.assert_not_called()
        self.reloj.return_value += timedelta(seconds=5)
        self.assertEqual(self.client.get("/api/v1/salud/").status_code, 200)
        jornada.refresh_from_db()
        self.assertEqual(jornada.estado, "FINALIZADA")

    def test_error_parcial_del_procesador_no_se_marca_como_correcto(self):
        resultado = {"solicitudes_cerradas": 0, "jornadas_cerradas": 0, "errores": 1}
        with patch.object(recuperacion, "procesar_cierre_diario", return_value=resultado), self.assertLogs("vitago.api", level="WARNING"):
            self.assertFalse(self.recuperador.recuperar())

    def test_presupuesto_agotado_deja_pendientes_para_siguiente_ejecucion(self):
        jornada = self._jornada()
        with patch("apps.solicitudes.contingencias.time.monotonic", side_effect=[0, 6]):
            resultado = procesar_cierre_diario(self.ahora, recuperar_suspensiones=False, limite_segundos=5)
        self.assertTrue(resultado["pendiente"])
        jornada.refresh_from_db()
        self.assertEqual(jornada.estado, "ACTIVA")
        self.assertTrue(self.recuperador.recuperar())
        jornada.refresh_from_db()
        self.assertEqual(jornada.estado, "FINALIZADA")

    def test_una_jornada_que_no_pudo_cerrarse_impide_continuar(self):
        jornada = self._jornada()
        # Inconsistencia sintética: una asignación activa de hoy bajo jornada antigua.
        vigente = JornadaRepartidor(repartidor=self.repartidor, iniciada_en=self.ahora - timedelta(minutes=5))
        self._servicio(vigente)
        with self.assertLogs("vitago.api", level="WARNING"):
            self.assertFalse(self.recuperador.recuperar())
        jornada.refresh_from_db()
        self.assertEqual(jornada.estado, "ACTIVA")

    def test_puede_iniciar_hoy_despues_de_recuperacion_del_arranque(self):
        self._jornada()
        self.assertTrue(self.recuperador.recuperar())
        nueva = iniciar_jornada(self.repartidor.usuario, {})
        self.assertEqual(nueva.fecha_operativa, self.ahora.date())


@override_settings(HABILITAR_RECUPERACION_CIERRE=True, MODO_APLICACION="CORPORATIVO")
class PruebasIntegracionArranque(SimpleTestCase):
    def test_candado_ocupado_no_permite_operar_ni_libera_el_de_otro_hilo(self):
        recuperador = recuperacion.RecuperadorCierreOperativo()
        recuperador._candado = Mock()
        recuperador._candado.acquire.return_value = False
        with patch.object(recuperacion, "procesar_cierre_diario") as procesar:
            self.assertFalse(recuperador.recuperar())
        procesar.assert_not_called()
        recuperador._candado.release.assert_not_called()

    def test_wsgi_y_asgi_invocan_recuperacion_despues_de_crear_aplicacion(self):
        for tipo in ("wsgi", "asgi"):
            with self.subTest(tipo=tipo), patch(f"django.core.{tipo}.get_{tipo}_application") as crear, patch.object(recuperacion, "recuperar_al_arrancar") as recuperar:
                modulo = importlib.import_module(f"config.{tipo}")
                crear.reset_mock(); recuperar.reset_mock()
                importlib.reload(modulo)
                crear.assert_called_once_with()
                recuperar.assert_called_once_with()

    def test_arranque_cierra_conexiones_para_no_heredarlas_al_fork(self):
        conexion = Mock(in_atomic_block=False)
        with patch.object(recuperacion, "recuperar_cierres_operativos", return_value=True) as recuperar, patch.object(recuperacion.connections, "all", return_value=[conexion]):
            recuperacion.recuperar_al_arrancar()
        recuperar.assert_called_once_with(forzar=True)
        conexion.close.assert_called_once_with()

    @override_settings(HABILITAR_RECUPERACION_CIERRE=False)
    def test_comandos_y_pruebas_pueden_omitir_recuperacion_sin_base(self):
        with patch.object(recuperacion, "procesar_cierre_diario") as procesar:
            recuperacion.recuperar_al_arrancar()
            self.assertTrue(recuperacion.RecuperadorCierreOperativo().recuperar())
        procesar.assert_not_called()

    def test_middleware_no_entrega_solicitud_si_cierre_no_esta_listo(self):
        vista = Mock(return_value=HttpResponse("ejecutada"))
        middleware = MiddlewareRecuperacionCierre(vista)
        with patch.object(recuperacion, "recuperar_cierres_operativos", return_value=False):
            respuesta = middleware(RequestFactory().post("/api/v1/autenticacion/iniciar-sesion/"))
        self.assertEqual(respuesta.status_code, 503)
        vista.assert_not_called()

    def test_archivos_estaticos_no_ejecutan_cierres(self):
        middleware = MiddlewareRecuperacionCierre(lambda solicitud: HttpResponse())
        with patch.object(recuperacion, "recuperar_cierres_operativos") as recuperar:
            self.assertEqual(middleware(RequestFactory().get("/static/icono.png")).status_code, 200)
        recuperar.assert_not_called()

    def test_hilos_comparten_revision_y_no_procesan_dos_veces(self):
        listo, liberar = threading.Event(), threading.Event()
        ahora = datetime(2026, 10, 30, 14, tzinfo=ZoneInfo("UTC"))
        def procesar(*args, **kwargs):
            listo.set()
            if not liberar.wait(5):
                raise AssertionError("La prueba no liberó la recuperación.")
            return {"solicitudes_cerradas": 0, "jornadas_cerradas": 0}
        recuperador = recuperacion.RecuperadorCierreOperativo()
        with patch.object(recuperacion, "procesar_cierre_diario", side_effect=procesar) as ejecutar, patch.object(recuperacion, "_limite_revision", return_value=ahora + timedelta(minutes=1)), patch.object(recuperacion, "_hay_jornadas_vencidas", return_value=False), patch("django.utils.timezone.now", return_value=ahora):
            with ThreadPoolExecutor(max_workers=2) as grupo:
                primero = grupo.submit(recuperador.recuperar)
                try:
                    self.assertTrue(listo.wait(3))
                    segundo = grupo.submit(recuperador.recuperar)
                finally:
                    liberar.set()
                self.assertTrue(primero.result(5))
                self.assertTrue(segundo.result(5))
        ejecutar.assert_called_once()
