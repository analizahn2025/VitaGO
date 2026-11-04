"""Política temporal de proximidad, contratos, alcance y desactivación."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.seguimiento.captura import captura_cercana_para_paradas, configuracion_captura_cercana
from apps.seguimiento.tests import test_llegadas as datos_llegadas
from apps.seguimiento.tests import test_seguimiento as datos
from apps.usuarios.models import Rol, RolUsuario


class PruebasPoliticaCapturaCercana(SimpleTestCase):
    def _parada(self, tipo="RECOLECCION", estado="GOING_TO_PICKUP"):
        return {
            "solicitud_id": uuid4(), "tipo": tipo, "estado_solicitud": estado,
            "ubicacion": SimpleNamespace(pk=uuid4(), latitud="14.072300", longitud="-87.192100"),
        }

    def test_solo_proxima_parada_puede_ser_objetivo(self):
        primera, segunda = self._parada(), self._parada("ENTREGA", "IN_TRANSIT")
        politica = captura_cercana_para_paradas([primera, segunda], jornada_vigente=True)
        self.assertEqual(politica["objetivo"]["solicitud_id"], primera["solicitud_id"])
        primera["estado_solicitud"] = "AT_PICKUP"
        self.assertIsNone(captura_cercana_para_paradas([primera, segunda], jornada_vigente=True)["objetivo"])

    def test_sin_jornada_sin_paradas_y_destino_especial_desactivan(self):
        especial = self._parada("ENVIO_ESPECIAL", "IN_TRANSIT")
        especial["ubicacion"] = None
        for paradas, vigente in (([], True), ([self._parada()], False), ([especial], True)):
            politica = captura_cercana_para_paradas(paradas, jornada_vigente=vigente)
            self.assertFalse(politica["habilitada"])
            self.assertIsNone(politica["objetivo"])

    @override_settings(LLEGADAS_AUTOMATICAS_HABILITADAS=False)
    def test_interruptor_de_llegadas_desactiva_captura_cercana(self):
        politica = captura_cercana_para_paradas([self._parada()], jornada_vigente=True)
        self.assertFalse(politica["habilitada"])
        self.assertIsNone(politica["objetivo"])

    @override_settings(INTERVALO_GPS_CAPTURA_MOVIMIENTO_SEGUNDOS=2, INTERVALO_GPS_ENVIO_SEGUNDOS=3)
    def test_no_ralentiza_intervalos_normales_mas_frecuentes(self):
        politica = configuracion_captura_cercana()
        self.assertEqual(politica["intervalo_captura_segundos"], 2)
        self.assertEqual(politica["intervalo_envio_segundos"], 3)


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasAPICapturaCercana(TestCase):
    setUpTestData = classmethod(datos.PruebasSeguimiento.setUpTestData.__func__)
    _preparar_estado = datos_llegadas.PruebasLlegadasAutomaticas._preparar_estado
    _cliente = datos_llegadas.PruebasLlegadasAutomaticas._cliente

    def setUp(self):
        ahora = timezone.now().astimezone(ZoneInfo("America/Tegucigalpa")).replace(hour=12, minute=0, second=0)
        self.enterContext(patch("django.utils.timezone.now", return_value=ahora))
        datos_llegadas.PruebasLlegadasAutomaticas.setUp(self)

    def _ruta(self):
        return self._cliente().get(reverse("rutas:mi-ruta"))

    def test_contrato_cercano_conserva_configuracion_y_no_hace_sql_adicional(self):
        configuracion = self._cliente().get(reverse("seguimiento:configuracion")).json()
        self.assertEqual(configuracion["intervalo_captura_detenido_segundos"], 15)
        self.assertEqual(configuracion["intervalo_envio_segundos"], 20)
        cercana = configuracion["llegada_automatica"]["captura_cercana"]
        self.assertEqual((cercana["intervalo_captura_segundos"], cercana["intervalo_envio_segundos"]), (5, 5))
        with CaptureQueriesContext(connection) as consultas:
            respuesta = self._ruta()
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertLessEqual(len(consultas), 10)
        politica = respuesta.json()["captura_cercana"]
        self.assertTrue(politica["habilitada"])
        self.assertEqual(politica["objetivo"], {
            "solicitud_id": str(self.solicitud.pk), "tipo_parada": "RECOLECCION",
            "ubicacion_id": str(self.origen.pk), "latitud": str(self.origen.latitud), "longitud": str(self.origen.longitud),
        })
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, "GOING_TO_PICKUP")

    def test_llegada_confirmada_retira_objetivo_y_entrega_usa_destino(self):
        self._preparar_estado("AT_PICKUP")
        self.assertIsNone(self._ruta().json()["captura_cercana"]["objetivo"])
        self._preparar_estado("IN_TRANSIT")
        objetivo = self._ruta().json()["captura_cercana"]["objetivo"]
        self.assertEqual(objetivo["tipo_parada"], "ENTREGA")
        self.assertEqual(objetivo["ubicacion_id"], str(self.destino.pk))

    def test_jornada_vencida_o_motorista_pausado_no_activan(self):
        self.repartidor.estado_operativo = "PAUSED"
        self.repartidor.save(update_fields=("estado_operativo",))
        self.assertFalse(self._ruta().json()["captura_cercana"]["habilitada"])
        self.repartidor.estado_operativo = "ON_ROUTE"
        self.repartidor.save(update_fields=("estado_operativo",))
        self.jornada.cierre_programado_en = self.ahora - timedelta(minutes=1)
        self.jornada.save(update_fields=("cierre_programado_en",))
        self.assertFalse(self._ruta().json()["captura_cercana"]["habilitada"])

    def test_sin_jornada_no_envia_objetivo(self):
        self.jornada.estado = "FINALIZADA"
        self.jornada.finalizada_en = self.ahora
        self.jornada.save(update_fields=("estado", "finalizada_en"))
        self.assertFalse(self._ruta().json()["captura_cercana"]["habilitada"])

    def test_otro_usuario_no_puede_leer_objetivo_del_motorista(self):
        respuesta = self._cliente(self.solicitante).get(reverse("rutas:mi-ruta"))
        self.assertEqual(respuesta.status_code, 404)

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_publica_misma_politica_para_rol_global(self):
        RolUsuario.objetos.filter(usuario=self.usuario_repartidor).update(activo=False, revocado_en=self.ahora)
        self.usuario_repartidor.empresa = None
        self.usuario_repartidor.save(update_fields=("empresa",))
        self.repartidor.vehiculo.empresa = None
        self.repartidor.vehiculo.save(update_fields=("empresa",))
        self.repartidor.empresa = None
        self.repartidor.save(update_fields=("empresa",))
        RolUsuario.objetos.create(usuario=self.usuario_repartidor, rol=Rol.objetos.get(codigo="REPARTIDOR_RED"),
            tipo_alcance="GLOBAL", asignado_por=self.administrador)
        respuesta = self._ruta()
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertTrue(respuesta.json()["captura_cercana"]["habilitada"])
        self.assertEqual(respuesta.json()["captura_cercana"]["intervalo_envio_segundos"], 5)
