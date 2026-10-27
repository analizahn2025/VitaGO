"""Limpieza sin red, sin perder auditoría y compatible con pythonw.exe."""

from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.rutas.management.commands.limpiar_rutas_google_vencidas import Command
from apps.rutas.models import CalculoRutaVial, ConsumoRutasGoogle, VersionRuta
from apps.rutas.servicios import sincronizar_ruta
from apps.rutas.tests import test_mi_ruta as datos_ruta
from apps.solicitudes.models import Solicitud


class PruebasComandoLimpiezaGoogle(SimpleTestCase):
    @patch("apps.rutas.management.commands.limpiar_rutas_google_vencidas.limpiar_geometria_vencida", return_value=3)
    def test_informa_resultado_en_consola_y_registro(self, limpiar):
        salida = StringIO()
        with self.assertLogs("vitago.api", level="INFO") as registros:
            call_command("limpiar_rutas_google_vencidas", stdout=salida)
        limpiar.assert_called_once_with()
        self.assertIn("eliminadas: 3", salida.getvalue())
        self.assertIn("eliminadas: 3", registros.output[0])

    @patch("apps.rutas.management.commands.limpiar_rutas_google_vencidas.limpiar_geometria_vencida", return_value=0)
    def test_pythonw_sin_stdout_conserva_registro(self, limpiar):
        with patch("sys.stdout", None):
            comando = Command()
        with self.assertLogs("vitago.api", level="INFO") as registros:
            call_command(comando, confirmar_corporativo=True)
        limpiar.assert_called_once_with()
        self.assertIn("eliminadas: 0", registros.output[0])

    @override_settings(MODO_APLICACION="EXTERNO")
    @patch("apps.rutas.management.commands.limpiar_rutas_google_vencidas.limpiar_geometria_vencida")
    def test_confirmacion_corporate_rechaza_network_antes_de_limpiar(self, limpiar):
        with self.assertRaisesMessage(CommandError, "no puede ejecutar limpieza en Network"):
            call_command("limpiar_rutas_google_vencidas", confirmar_corporativo=True, stdout=StringIO())
        limpiar.assert_not_called()

    @override_settings(MODO_APLICACION="EXTERNO")
    @patch("apps.rutas.management.commands.limpiar_rutas_google_vencidas.limpiar_geometria_vencida", return_value=0)
    def test_comando_manual_generico_sigue_admitiendo_network(self, limpiar):
        call_command("limpiar_rutas_google_vencidas", stdout=StringIO())
        limpiar.assert_called_once_with()

    @patch("apps.rutas.management.commands.limpiar_rutas_google_vencidas.limpiar_geometria_vencida", side_effect=RuntimeError("Fallo sintético"))
    def test_fallo_se_registra_y_no_se_oculta(self, limpiar):
        with self.assertLogs("vitago.api", level="ERROR") as registros:
            with self.assertRaisesMessage(RuntimeError, "Fallo sintético"):
                call_command("limpiar_rutas_google_vencidas", stdout=StringIO())
        self.assertIn("Falló la limpieza", registros.output[0])


@override_settings(MODO_APLICACION="CORPORATIVO")
class PruebasPersistenciaLimpiezaGoogle(TestCase):
    setUpTestData = classmethod(datos_ruta.PruebasMiRuta.setUpTestData.__func__)
    motorista = datos_ruta.PruebasMiRuta.motorista
    _crear_solicitud = datos_ruta.PruebasMiRuta._crear_solicitud

    def setUp(self):
        self.sin_red = self.enterContext(patch(
            "apps.rutas.proveedor_google.urlopen",
            side_effect=AssertionError("La limpieza no debe consultar Google."),
        ))
        self.ahora = timezone.now()
        self.solicitud = self._crear_solicitud("LIMPIEZA-PRUEBA")
        self.ruta = sincronizar_ruta(self.motorista, VersionRuta.Motivo.ASIGNACION)
        self.version = self.ruta.versiones.get()
        self.contador = ConsumoRutasGoogle.objects.create(
            periodo="DIARIO", fecha=timezone.localdate(), intentos_reservados=4,
        )

    def _calculo(self, expira_en, *, version=None, geometria="????????"):
        return CalculoRutaVial.objects.create(
            version=version or self.version, estado="CALCULADA", token_intento=uuid4(),
            iniciada_en=self.ahora - timedelta(days=2), calculada_en=self.ahora - timedelta(days=2),
            expira_en=expira_en, polilinea_codificada=geometria,
            origen_gps={"origen": "fixture"}, paradas_calculadas=[{"solicitud_id": str(self.solicitud.pk)}],
        )

    def test_elimina_solo_geometria_vencida_y_conserva_toda_la_auditoria(self):
        calculo = self._calculo(self.ahora - timedelta(seconds=1))
        anterior = CalculoRutaVial.objects.values().get(pk=calculo.pk)
        paradas = list(self.version.paradas.values())
        with patch("apps.rutas.ruta_vial.timezone.now", return_value=self.ahora):
            call_command("limpiar_rutas_google_vencidas", confirmar_corporativo=True, stdout=StringIO())
        posterior = CalculoRutaVial.objects.values().get(pk=calculo.pk)
        self.assertTrue(anterior.pop("polilinea_codificada"))
        self.assertEqual(posterior.pop("polilinea_codificada"), "")
        self.assertEqual(anterior, posterior)
        self.assertEqual(list(self.version.paradas.values()), paradas)
        self.assertTrue(Solicitud.objects.filter(pk=self.solicitud.pk).exists())
        self.contador.refresh_from_db()
        self.assertEqual(self.contador.intentos_reservados, 4)
        self.sin_red.assert_not_called()

    def test_corte_exacto_limpia_pero_no_toca_vigentes_ni_fecha_nula(self):
        al_corte = self._calculo(self.ahora)
        versiones = [VersionRuta.objects.create(ruta=self.ruta, numero=n, motivo="CAMBIO_ESTADO") for n in (2, 3)]
        vigente = self._calculo(self.ahora + timedelta(hours=1), version=versiones[0])
        sin_fecha = self._calculo(None, version=versiones[1])
        with patch("apps.rutas.ruta_vial.timezone.now", return_value=self.ahora):
            call_command("limpiar_rutas_google_vencidas", stdout=StringIO())
        for calculo in (al_corte, vigente, sin_fecha):
            calculo.refresh_from_db()
        self.assertEqual(al_corte.polilinea_codificada, "")
        self.assertEqual(vigente.polilinea_codificada, "????????")
        self.assertEqual(sin_fecha.polilinea_codificada, "????????")
        self.sin_red.assert_not_called()

    def test_segunda_ejecucion_es_idempotente(self):
        self._calculo(self.ahora - timedelta(seconds=1))
        salidas = []
        for _ in range(2):
            salida = StringIO()
            call_command("limpiar_rutas_google_vencidas", stdout=salida)
            salidas.append(salida.getvalue())
        self.assertIn("eliminadas: 1", salidas[0])
        self.assertIn("eliminadas: 0", salidas[1])
        self.assertEqual(CalculoRutaVial.objects.count(), 1)
        self.sin_red.assert_not_called()
