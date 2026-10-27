"""El cálculo no depende de la puntualidad de la tarea de cierre diario."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.jornadas.models import JornadaRepartidor
from apps.rutas.models import CalculoRutaVial, ConsumoRutasGoogle
from apps.rutas.tests import test_ruta_vial as datos
from apps.seguimiento.models import RegistroUbicacion
from apps.solicitudes.models import Solicitud
from apps.solicitudes.vigencia import limite_dia_operativo


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL",
                   HABILITAR_RUTAS_GOOGLE=True, CLAVE_API_GOOGLE_MAPS="solo-pruebas")
class PruebasCorteCalculo(TestCase):
    setUpTestData = classmethod(datos.PruebasRutaVial.setUpTestData.__func__)
    motorista = datos.PruebasRutaVial.motorista
    _crear_solicitud = datos.PruebasRutaVial._crear_solicitud
    _cliente = datos.PruebasRutaVial._cliente
    calcular = datos.PruebasRutaVial.calcular
    setUp = datos.PruebasRutaVial.setUp

    def _preparar_corte(self):
        inicio = timezone.now() - timedelta(days=1)
        self.corte = limite_dia_operativo(inicio, self.motorista.empresa)
        JornadaRepartidor.objects.filter(pk=self.jornada.pk).update(iniciada_en=inicio)
        Solicitud.objects.filter(pk=self.solicitud.pk).update(creado_en=inicio)
        RegistroUbicacion.objects.filter(pk=self.punto.pk).update(registrada_en=self.corte - timedelta(seconds=5))

    def test_dia_vencido_rechaza_sin_reservar_ni_llamar(self):
        self._preparar_corte()
        with patch("django.utils.timezone.now", return_value=self.corte + timedelta(seconds=10)), \
                patch("apps.rutas.ruta_vial.calcular_ruta_google") as proveedor:
            respuesta = self.calcular()
        self.assertEqual(respuesta.status_code, 409)
        self.assertEqual(respuesta.data["codigo"], "DIA_OPERATIVO_FINALIZADO")
        proveedor.assert_not_called()
        self.assertFalse(CalculoRutaVial.objects.exists())
        self.assertFalse(ConsumoRutasGoogle.objects.exists())

    def test_jornada_vencida_rechaza_aunque_servicio_sea_de_hoy(self):
        self._preparar_corte()
        Solicitud.objects.filter(pk=self.solicitud.pk).update(creado_en=self.corte + timedelta(seconds=1))
        with patch("django.utils.timezone.now", return_value=self.corte + timedelta(seconds=10)), \
                patch("apps.rutas.ruta_vial.calcular_ruta_google") as proveedor:
            respuesta = self.calcular()
        self.assertEqual(respuesta.status_code, 409)
        proveedor.assert_not_called()
        self.assertFalse(ConsumoRutasGoogle.objects.exists())

    def test_servicio_vencido_rechaza_con_jornada_del_dia_actual(self):
        self._preparar_corte()
        JornadaRepartidor.objects.filter(pk=self.jornada.pk).update(iniciada_en=self.corte)
        RegistroUbicacion.objects.filter(pk=self.punto.pk).update(registrada_en=self.corte + timedelta(seconds=1))
        with patch("django.utils.timezone.now", return_value=self.corte + timedelta(seconds=10)), \
                patch("apps.rutas.ruta_vial.calcular_ruta_google") as proveedor:
            respuesta = self.calcular()
        self.assertEqual(respuesta.status_code, 409)
        proveedor.assert_not_called()

    def test_respuesta_que_cruza_medianoche_no_publica_geometria(self):
        self._preparar_corte()
        with patch("django.utils.timezone.now", return_value=self.corte - timedelta(seconds=1)) as reloj:
            def responder(*args):
                reloj.return_value = self.corte + timedelta(seconds=1)
                return datos.RESULTADO
            with patch("apps.rutas.ruta_vial.calcular_ruta_google", side_effect=responder) as proveedor:
                respuesta = self.calcular()
        self.assertEqual(respuesta.status_code, 409)
        self.assertEqual(respuesta.data["codigo"], "DIA_OPERATIVO_FINALIZADO")
        proveedor.assert_called_once()
        calculo = CalculoRutaVial.objects.get()
        self.assertEqual(calculo.estado, "FALLIDA")
        self.assertEqual(calculo.codigo_error, "DIA_OPERATIVO_FINALIZADO")
        self.assertEqual(calculo.polilinea_codificada, "")
        self.assertIsNone(calculo.expira_en)
        self.assertEqual(list(ConsumoRutasGoogle.objects.values_list("intentos_reservados", flat=True)), [1, 1])

    def test_ruta_reutilizada_tambien_respeta_corte(self):
        self._preparar_corte()
        with patch("django.utils.timezone.now", return_value=self.corte - timedelta(seconds=1)), \
                patch("apps.rutas.ruta_vial.calcular_ruta_google", return_value=datos.RESULTADO):
            self.assertEqual(self.calcular().status_code, 200)
        with patch("django.utils.timezone.now", return_value=self.corte), \
                patch("apps.rutas.ruta_vial.calcular_ruta_google") as proveedor:
            respuesta = self.calcular()
        self.assertEqual(respuesta.status_code, 409)
        proveedor.assert_not_called()

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_conserva_calculo_fuera_del_corte_corporativo(self):
        self._preparar_corte()
        with patch("django.utils.timezone.now", return_value=self.corte + timedelta(seconds=10)), \
                patch("apps.rutas.ruta_vial.calcular_ruta_google", return_value=datos.RESULTADO) as proveedor:
            respuesta = self.calcular()
        self.assertEqual(respuesta.status_code, 200)
        proveedor.assert_called_once()
