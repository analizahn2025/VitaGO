"""Diagnóstico acotado de frecuencia de captura, independiente del envío."""

from datetime import timedelta
from uuid import uuid4

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.jornadas.models import JornadaRepartidor
from apps.jornadas.opciones import EstadoJornada
from apps.repartidores.models import Repartidor
from apps.seguimiento.models import RegistroUbicacion
from apps.seguimiento.selectores import _diagnosticar_captura_gps, obtener_configuracion_gps
from apps.seguimiento.tests import test_seguimiento as datos_seguimiento
from apps.usuarios.models import Usuario


@override_settings(
    MODO_APLICACION="CORPORATIVO",
    PROVEEDOR_AUTENTICACION="LOCAL",
    INTERVALO_GPS_MAXIMO_SEGUNDOS=30,
)
class PruebasDiagnosticoCaptura(TestCase):
    @classmethod
    def setUpTestData(cls):
        datos_seguimiento.PruebasSeguimiento.setUpTestData.__func__(cls)

    def setUp(self):
        self.ahora = timezone.now()
        self.inicio = self.ahora - timedelta(minutes=30)
        self.jornada = JornadaRepartidor.objects.create(
            repartidor=self.repartidor, iniciada_en=self.inicio
        )

    def _puntos(self, segundos, *, jornada=None, repartidor=None):
        return RegistroUbicacion.objects.bulk_create([
            RegistroUbicacion(
                id_cliente=uuid4(),
                repartidor=repartidor or self.repartidor,
                jornada=jornada or self.jornada,
                latitud="14.075000", longitud="-87.190000",
                registrada_en=self.inicio + timedelta(seconds=segundo),
            )
            for segundo in segundos
        ])

    def _diagnostico(self):
        return obtener_configuracion_gps(self.usuario_repartidor)["diagnostico_captura"]

    def test_lote_recibido_junto_con_capturas_cada_cinco_segundos_no_alarma(self):
        # La recepción conjunta ocurre mucho después de las capturas: importa
        # registrada_en, no creado_en ni el espacio entre peticiones HTTP.
        puntos = self._puntos(range(0, 100, 5))
        self.assertTrue(all(punto.creado_en > punto.registrada_en for punto in puntos))
        diagnostico = self._diagnostico()
        self.assertEqual(diagnostico["muestra_puntos"], 20)
        self.assertEqual(diagnostico["intervalos_evaluados"], 19)
        self.assertEqual(diagnostico["intervalos_fuera_umbral"], 0)
        self.assertEqual(diagnostico["intervalo_maximo_observado_segundos"], 5)
        self.assertFalse(diagnostico["requiere_ajuste_captura"])
        self.assertIsNone(diagnostico["mensaje"])

    def test_hueco_de_37_segundos_advierte_sin_modificar_registros(self):
        self._puntos([0, 5, 42, 47])
        antes = list(RegistroUbicacion.objects.values())
        diagnostico = self._diagnostico()
        self.assertEqual(diagnostico["intervalos_evaluados"], 3)
        self.assertEqual(diagnostico["intervalos_fuera_umbral"], 1)
        self.assertEqual(diagnostico["intervalo_maximo_observado_segundos"], 37)
        self.assertTrue(diagnostico["requiere_ajuste_captura"])
        self.assertIn("captura en la aplicación", diagnostico["mensaje"])
        self.assertEqual(list(RegistroUbicacion.objects.values()), antes)

    def test_sin_puntos_devuelve_ceros_y_maximo_nulo(self):
        self.assertEqual(self._diagnostico(), {
            "muestra_puntos": 0,
            "intervalos_evaluados": 0,
            "intervalos_fuera_umbral": 0,
            "intervalo_maximo_observado_segundos": None,
            "requiere_ajuste_captura": False,
            "mensaje": None,
            "umbral_segundos": 30,
        })

    def test_sin_jornada_activa_no_incluye_puntos_historicos(self):
        self._puntos([0, 120])
        self.jornada.estado = EstadoJornada.FINALIZADA
        self.jornada.finalizada_en = self.ahora
        self.jornada.save(update_fields=["estado", "finalizada_en"])
        self.assertEqual(self._diagnostico()["muestra_puntos"], 0)

    def test_un_solo_punto_no_fabrica_un_intervalo(self):
        self._puntos([0])
        diagnostico = self._diagnostico()
        self.assertEqual(diagnostico["muestra_puntos"], 1)
        self.assertEqual(diagnostico["intervalos_evaluados"], 0)
        self.assertIsNone(diagnostico["intervalo_maximo_observado_segundos"])

    def test_tiempos_iguales_no_cuentan_como_intervalos(self):
        self._puntos([0, 0, 5, 5])
        diagnostico = self._diagnostico()
        self.assertEqual(diagnostico["muestra_puntos"], 4)
        self.assertEqual(diagnostico["intervalos_evaluados"], 1)
        self.assertEqual(diagnostico["intervalo_maximo_observado_segundos"], 5)

    def test_umbral_exacto_no_alarma_y_orden_de_recepcion_no_importa(self):
        self._puntos([60, 0, 30])
        diagnostico = self._diagnostico()
        self.assertEqual(diagnostico["intervalos_evaluados"], 2)
        self.assertEqual(diagnostico["intervalos_fuera_umbral"], 0)
        self.assertFalse(diagnostico["requiere_ajuste_captura"])

    def test_solo_ultimos_60_puntos_con_consulta_acotada(self):
        # Un hueco viejo no altera el diagnóstico de la muestra actual.
        self._puntos([0, *range(600, 950, 5)])
        with self.assertNumQueries(1) as consultas:
            diagnostico = _diagnosticar_captura_gps(self.repartidor)
        self.assertIn("LIMIT 60", consultas.captured_queries[0]["sql"].upper())
        self.assertEqual(diagnostico["muestra_puntos"], 60)
        self.assertEqual(diagnostico["intervalos_evaluados"], 59)
        self.assertEqual(diagnostico["intervalos_fuera_umbral"], 0)

    def test_jornada_ajena_no_aporta_puntos_ni_datos_crudos(self):
        otro_usuario = Usuario.objetos.create(
            correo="otro-diagnostico@example.test", nombres="Otro", apellidos="Motorista",
            empresa=self.empresa,
        )
        otro_repartidor = Repartidor.objects.create(
            usuario=otro_usuario, empresa=self.empresa
        )
        otra_jornada = JornadaRepartidor.objects.create(
            repartidor=otro_repartidor, iniciada_en=self.inicio
        )
        self._puntos([0, 100], jornada=otra_jornada, repartidor=otro_repartidor)
        cliente = APIClient()
        cliente.force_authenticate(self.usuario_repartidor)
        respuesta = cliente.get(reverse("seguimiento:configuracion"))
        self.assertEqual(respuesta.status_code, 200)
        diagnostico = respuesta.json()["diagnostico_captura"]
        self.assertEqual(diagnostico["muestra_puntos"], 0)
        texto = str(diagnostico)
        for privado in (str(otro_repartidor.pk), str(otra_jornada.pk), "14.075000", "-87.190000"):
            self.assertNotIn(privado, texto)

    def test_configuracion_conserva_captura_movimiento_envio_y_umbral(self):
        configuracion = obtener_configuracion_gps(self.usuario_repartidor)
        self.assertEqual(configuracion["intervalo_captura_movimiento_segundos"], 5)
        self.assertEqual(configuracion["intervalo_captura_detenido_segundos"], 15)
        self.assertEqual(configuracion["intervalo_envio_segundos"], 20)
        self.assertEqual(configuracion["intervalo_maximo_medicion_segundos"], 30)
