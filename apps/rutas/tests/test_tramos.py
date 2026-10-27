"""Geometría por envío/etapa, sin modificar orden ni llamar a Google real."""

import json
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.rutas.models import CalculoRutaVial, ConsumoRutasGoogle, VersionRuta
from apps.rutas.proveedor_google import ErrorProveedorGoogle, calcular_ruta_google
from apps.rutas.ruta_vial import limpiar_geometria_vencida
from apps.rutas.servicios import sincronizar_ruta
from apps.rutas.tests import test_ruta_vial as datos_ruta
from apps.solicitudes.models import Solicitud
from apps.solicitudes.opciones import EstadoSolicitud, ModalidadSolicitud, PrioridadSolicitud


# Geometrías SINTÉTICAS de pruebas, no trayectos reales de ninguna ubicación.
LINEAS = ["????", "??????", "????????", "??????????"]


def respuesta_simulada(origen, destinos):
    return {**datos_ruta.RESULTADO, "polilineas_tramos": [LINEAS[i % len(LINEAS)] for i in range(len(destinos))]}


@override_settings(MODO_APLICACION="CORPORATIVO", HABILITAR_RUTAS_GOOGLE=True,
                   CLAVE_API_GOOGLE_MAPS="solo-pruebas", RUTAS_GOOGLE_INTENTOS_POR_VERSION=2)
class PruebasTramosPorEnvio(TestCase):
    setUpTestData = classmethod(datos_ruta.PruebasRutaVial.setUpTestData.__func__)
    motorista = datos_ruta.PruebasRutaVial.motorista
    _crear_solicitud = datos_ruta.PruebasRutaVial._crear_solicitud
    _cliente = datos_ruta.PruebasRutaVial._cliente
    calcular = datos_ruta.PruebasRutaVial.calcular

    def setUp(self):
        datos_ruta.PruebasRutaVial.setUp(self)
        self.proveedor = self.enterContext(patch("apps.rutas.ruta_vial.calcular_ruta_google", side_effect=respuesta_simulada))
        self.red = self.enterContext(patch("apps.rutas.proveedor_google.urlopen", side_effect=AssertionError("Sin Google real.")))

    def _leer(self):
        respuesta = self.cliente.get(reverse("rutas:mi-ruta"))
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        return respuesta.data

    def _dos_envios(self):
        self.segunda = self._crear_solicitud("SOL-TRAMOS-2", minutos_atras=0)
        sincronizar_ruta(self.motorista, VersionRuta.Motivo.ASIGNACION)
        respuesta = self.calcular(version_actual=2)
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        return respuesta.data

    def test_calculo_entrega_recoleccion_y_entrega_con_lineas_distintas(self):
        respuesta = self.calcular()
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        datos = respuesta.data
        self.assertEqual(datos["modo_visualizacion"], "UN_TRAMO")
        self.assertTrue(datos["desglose_disponible"])
        self.assertFalse(datos["requiere_actualizar_desglose"])
        self.assertEqual([p["polilinea_codificada"] for p in datos["tramos"]], LINEAS[:2])
        self.assertEqual([p["tipo_parada"] for p in datos["tramos"]], ["RECOLECCION", "ENTREGA"])
        self.assertEqual([p["es_proximo"] for p in datos["tramos"]], [True, False])
        self.assertEqual(datos["tramo_actual_id"], f"{self.solicitud.pk}:RECOLECCION")
        self.assertEqual(datos["tramos"][0]["origen"]["tipo"], "GPS")
        self.assertEqual(datos["tramos"][1]["origen"]["ubicacion_id"], str(self.origen.pk))
        self.proveedor.assert_called_once()

    def test_dos_envios_se_identifican_sin_mezclar_sus_tramos(self):
        datos = self._dos_envios()
        self.assertEqual(len(datos["tramos"]), 4)
        self.assertEqual([p["orden_envio"] for p in datos["tramos"]], [1, 2, 1, 2])
        self.assertEqual([p["orden_parada"] for p in datos["tramos"]], [1, 2, 3, 4])
        self.assertEqual([p["solicitud_id"] for p in datos["tramos"]],
                         [str(self.solicitud.pk), str(self.segunda.pk)] * 2)
        self.assertEqual(datos["tramos"][2]["origen"]["ubicacion_id"], str(self.origen.pk))
        self.assertEqual([p["polilinea_codificada"] for p in datos["tramos"]],
                         [LINEAS[0], None, LINEAS[1], None])
        self.assertEqual(self.proveedor.call_count, 1)

    def test_consultar_otro_envio_no_mueve_estados_ni_cambia_proxima_parada(self):
        datos = self._dos_envios()
        estado = list(Solicitud.objects.order_by("pk").values())
        for _ in range(3):
            lectura = self._leer()
            seleccion = [p for p in lectura["ruta_vial"]["tramos"] if p["solicitud_id"] == str(self.segunda.pk)]
            self.assertEqual(len(seleccion), 2)
            self.assertTrue(all(not p["es_proximo"] for p in seleccion))
            self.assertEqual(lectura["proxima_parada"]["solicitud_id"], str(self.solicitud.pk))
            self.assertEqual(lectura["ruta_vial"]["tramo_actual_id"], datos["tramo_actual_id"])
        self.assertEqual(estado, list(Solicitud.objects.order_by("pk").values()))
        self.assertEqual(self.proveedor.call_count, 1)
        self.assertEqual(list(ConsumoRutasGoogle.objects.values_list("intentos_reservados", flat=True)), [1, 1])

    def test_recoger_pasa_a_entrega_sin_repetir_linea_de_recoleccion(self):
        datos = self.calcular().data
        Solicitud.objects.filter(pk=self.solicitud.pk).update(estado=EstadoSolicitud.RECOLECTADA)
        sincronizar_ruta(self.motorista, VersionRuta.Motivo.CAMBIO_ESTADO)
        lectura = self._leer()["ruta_vial"]
        self.assertEqual(lectura["tramo_actual_id"], f"{self.solicitud.pk}:ENTREGA")
        self.assertEqual(len(lectura["tramos"]), 1)
        self.assertEqual(lectura["tramos"][0]["polilinea_codificada"], datos["tramos"][1]["polilinea_codificada"])
        self.assertEqual(lectura["tramos"][0]["orden_parada"], 1)
        self.assertTrue(lectura["tramos"][0]["es_proximo"])
        self.proveedor.assert_called_once()

    def test_completar_recoleccion_activa_otro_envio_y_conserva_numeros_del_calculo(self):
        datos = self._dos_envios()
        Solicitud.objects.filter(pk=self.solicitud.pk).update(estado=EstadoSolicitud.RECOLECTADA)
        sincronizar_ruta(self.motorista, VersionRuta.Motivo.CAMBIO_ESTADO)
        lectura = self._leer()["ruta_vial"]
        self.assertEqual(lectura["tramo_actual_id"], f"{self.segunda.pk}:RECOLECCION")
        self.assertEqual([p["orden_envio"] for p in lectura["tramos"]], [2, 1, 2])
        self.assertEqual([p["polilinea_codificada"] for p in lectura["tramos"]], [None, LINEAS[1], None])
        self.assertEqual([p["tramo_id"] for p in lectura["tramos"]], [p["tramo_id"] for p in datos["tramos"]][1:])
        self.assertEqual(self.proveedor.call_count, 1)

    def test_retirar_paradas_intermedias_no_reutiliza_lineas_incompatibles(self):
        self._dos_envios()
        Solicitud.objects.filter(pk=self.solicitud.pk).update(estado=EstadoSolicitud.CANCELADA)
        sincronizar_ruta(self.motorista, VersionRuta.Motivo.CANCELACION)
        lectura = self._leer()["ruta_vial"]
        self.assertIsNone(lectura["tramo_actual_id"])
        self.assertIsNone(lectura["polilinea_codificada"])
        self.assertEqual(lectura["tramos"], [])
        self.assertEqual(self.proveedor.call_count, 1)

    def test_misma_ubicacion_no_repite_geometria_de_otra_etapa(self):
        Solicitud.objects.filter(pk=self.solicitud.pk).update(destino=self.origen)
        sincronizar_ruta(self.motorista, VersionRuta.Motivo.CAMBIO_ESTADO)
        respuesta = self.calcular(version_actual=2)
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertEqual(len(self.proveedor.call_args.args[1]), 1)
        self.assertEqual(len(respuesta.data["tramos"]), 2)
        entrega = respuesta.data["tramos"][1]
        self.assertTrue(entrega["sin_desplazamiento"])
        self.assertIsNone(entrega["polilinea_codificada"])
        Solicitud.objects.filter(pk=self.solicitud.pk).update(estado=EstadoSolicitud.RECOLECTADA)
        sincronizar_ruta(self.motorista, VersionRuta.Motivo.CAMBIO_ESTADO)
        lectura = self._leer()["ruta_vial"]
        self.assertEqual(lectura["tramo_actual_id"], entrega["tramo_id"])
        self.assertTrue(lectura["desglose_disponible"])
        self.assertTrue(lectura["tramos"][0]["sin_desplazamiento"])
        self.proveedor.assert_called_once()

    def test_sucursales_consecutivas_compartidas_no_reutilizan_viaje_terminado(self):
        self.segunda = self._crear_solicitud("SOL-MISMO-PUNTO", minutos_atras=0)
        Solicitud.objects.filter(pk=self.segunda.pk).update(origen=self.destino)
        sincronizar_ruta(self.motorista, VersionRuta.Motivo.ASIGNACION)
        datos = self.calcular(version_actual=2).data
        self.assertEqual(len(datos["tramos"]), 4)
        # D1=P2=D2, solo el primer movimiento hasta ese grupo tiene línea.
        self.assertTrue(datos["tramos"][2]["sin_desplazamiento"])
        self.assertIsNone(datos["tramos"][2]["polilinea_codificada"])
        self.assertTrue(datos["tramos"][3]["sin_desplazamiento"])
        self.assertEqual(len(self.proveedor.call_args.args[1]), 2)

    def test_datos_persistidos_solo_contienen_geometria_sin_metricas(self):
        self.calcular()
        calculo = CalculoRutaVial.objects.get()
        self.assertEqual(calculo.polilineas_tramos, LINEAS[:2])
        self.assertTrue(all(isinstance(linea, str) for linea in calculo.polilineas_tramos))
        valores = CalculoRutaVial.objects.values().get()
        self.assertNotIn("distancia_estimada_metros", valores)
        self.assertNotIn("duracion_estimada_segundos", valores)
        self.assertNotIn("legs", valores)

    def test_calculo_legacy_no_recorta_ni_llama_automaticamente(self):
        self.calcular()
        CalculoRutaVial.objects.update(polilineas_tramos=[])
        for datos in (self._leer()["ruta_vial"], self.calcular().data):
            self.assertFalse(datos["desglose_disponible"])
            self.assertTrue(datos["requiere_actualizar_desglose"])
            self.assertEqual(datos["tramos"], [])
            self.assertIsNone(datos["tramo_actual_id"])
        self.proveedor.assert_called_once()

    def test_actualizar_legacy_solo_explicito_y_consumo_unico(self):
        self.calcular()
        CalculoRutaVial.objects.update(polilineas_tramos=[])
        respuesta = self.calcular(reintentar=True)
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertTrue(respuesta.data["desglose_disponible"])
        self.assertEqual(CalculoRutaVial.objects.get().intentos, 2)
        self.assertEqual(self.proveedor.call_count, 2)
        self.assertEqual(self.calcular(reintentar=True).status_code, 200)
        self.assertEqual(self.proveedor.call_count, 2)
        self.assertEqual(list(ConsumoRutasGoogle.objects.values_list("intentos_reservados", flat=True)), [2, 2])

    def test_actualizacion_legacy_respeta_limite_y_no_borra_cache_vigente(self):
        self.calcular()
        CalculoRutaVial.objects.update(polilineas_tramos=[], intentos=2)
        respuesta = self.calcular(reintentar=True)
        self.assertEqual(respuesta.status_code, 409)
        self.assertEqual(respuesta.data["codigo"], "LIMITE_INTENTOS")
        self.assertTrue(CalculoRutaVial.objects.get().polilinea_codificada)
        self.proveedor.assert_called_once()

    def test_vencimiento_oculta_y_limpia_ambas_geometrias(self):
        self.calcular()
        CalculoRutaVial.objects.update(expira_en=timezone.now() - timedelta(seconds=1))
        datos = self._leer()["ruta_vial"]
        self.assertEqual(datos["tramos"], [])
        self.assertFalse(datos["desglose_disponible"])
        self.assertIsNone(datos["polilinea_codificada"])
        self.assertTrue(CalculoRutaVial.objects.get().polilineas_tramos)
        call_command("limpiar_rutas_google_vencidas", stdout=StringIO())
        calculo = CalculoRutaVial.objects.get()
        self.assertEqual(calculo.polilinea_codificada, "")
        self.assertEqual(calculo.polilineas_tramos, [])
        self.assertTrue(calculo.paradas_calculadas)
        self.assertEqual(self.calcular(reintentar=True).data["codigo"], "RUTA_VENCIDA")
        self.proveedor.assert_called_once()

    def test_limpieza_recupera_tramos_huerfanos_y_es_idempotente(self):
        self.calcular()
        CalculoRutaVial.objects.update(polilinea_codificada="", expira_en=timezone.now() - timedelta(seconds=1))
        self.assertEqual(limpiar_geometria_vencida(), 1)
        self.assertEqual(limpiar_geometria_vencida(), 0)
        self.assertEqual(CalculoRutaVial.objects.get().polilineas_tramos, [])

    def test_no_se_puede_enviar_seleccion_ni_origen_arbitrario_al_calcular(self):
        respuesta = self.calcular(solicitud_id=str(self.solicitud.pk), tramo_id="otro")
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("solicitud_id", respuesta.data)
        self.assertIn("tramo_id", respuesta.data)
        self.proveedor.assert_not_called()

    def test_prioritario_recogido_solo_publica_su_entrega(self):
        prioridad = self._crear_solicitud("SOL-TRAMOS-PRIORITY", prioridad=PrioridadSolicitud.PRIORITARIA,
                                          estado=EstadoSolicitud.RECOLECTADA)
        sincronizar_ruta(self.motorista, VersionRuta.Motivo.ASIGNACION)
        datos = self.calcular(version_actual=2).data
        self.assertEqual(len(datos["tramos"]), 1)
        self.assertEqual(datos["tramo_actual_id"], f"{prioridad.pk}:ENTREGA")
        self.assertNotIn(str(self.solicitud.pk), json.dumps(datos["tramos"]))

    def test_especial_no_publica_trazado_y_no_consulta(self):
        Solicitud.objects.filter(pk=self.solicitud.pk).update(estado=EstadoSolicitud.CANCELADA)
        self._crear_solicitud("SOL-TRAMOS-ESPECIAL", modalidad=ModalidadSolicitud.ESPECIAL)
        sincronizar_ruta(self.motorista, VersionRuta.Motivo.CAMBIO_ESTADO)
        datos = self._leer()["ruta_vial"]
        self.assertEqual(datos["tramos"], [])
        self.assertIsNone(datos["tramo_actual_id"])
        self.proveedor.assert_not_called()

    def test_terminal_sin_paradas_no_expone_geometria_anterior(self):
        self.calcular()
        Solicitud.objects.filter(pk=self.solicitud.pk).update(estado=EstadoSolicitud.ENTREGADA)
        lectura = self._leer()
        self.assertEqual(lectura["ruta_vial"]["estado"], "SIN_PARADAS")
        self.assertEqual(lectura["ruta_vial"]["tramos"], [])
        self.assertIsNone(lectura["ruta_vial"]["tramo_actual_id"])
        self.proveedor.assert_called_once()

    def test_otro_motorista_no_obtiene_tramos_ajenos(self):
        self.calcular()
        respuesta = self._cliente(self.motoristas[1].usuario).get(reverse("rutas:mi-ruta"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data["ruta_vial"]["tramos"], [])
        self.assertNotIn(str(self.solicitud.pk), respuesta.content.decode())

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_tambien_publica_tramos_sin_cambiar_contrato_base(self):
        self.assertEqual(self.calcular().status_code, 200)
        lectura = self._leer()
        self.assertEqual(len(lectura["ruta_vial"]["tramos"]), 2)
        self.assertEqual(lectura["mapa"]["modo"], "INTEGRADO")


@override_settings(HABILITAR_RUTAS_GOOGLE=True, CLAVE_API_GOOGLE_MAPS="solo-pruebas")
class PruebasProveedorTramos(SimpleTestCase):
    origen = {"latitud": "14.070000", "longitud": "-87.190000"}
    destinos = [{"latitud": "14.080000", "longitud": "-87.180000"},
                {"latitud": "14.090000", "longitud": "-87.170000"}]

    def _cuerpo(self, tramos):
        return json.dumps({"routes": [{"distanceMeters": 1800, "duration": "250.5s",
            "polyline": {"encodedPolyline": datos_ruta.RESULTADO["polilinea_codificada"]}, "legs": tramos}]}).encode()

    @patch("apps.rutas.proveedor_google.urlopen")
    def test_una_peticion_pide_polilineas_por_leg_sin_pedir_metricas_por_leg(self, abrir):
        abrir.return_value.__enter__.return_value.read.return_value = self._cuerpo(
            [{"polyline": {"encodedPolyline": linea}} for linea in LINEAS[:2]])
        resultado = calcular_ruta_google(self.origen, self.destinos)
        self.assertEqual(resultado["polilineas_tramos"], LINEAS[:2])
        solicitud = abrir.call_args.args[0]
        mascara = solicitud.get_header("X-goog-fieldmask")
        self.assertIn("routes.legs.polyline.encodedPolyline", mascara)
        self.assertNotIn("legs.duration", mascara)
        self.assertNotIn("legs.distance", mascara)
        cuerpo = json.loads(solicitud.data)
        self.assertEqual(len(cuerpo["intermediates"]), 1)
        self.assertEqual(cuerpo["destination"]["location"]["latLng"]["latitude"], 14.09)
        self.assertFalse(cuerpo["optimizeWaypointOrder"])
        self.assertNotIn("via", cuerpo["intermediates"][0])
        abrir.assert_called_once()

    @patch("apps.rutas.proveedor_google.urlopen")
    def test_rechaza_cantidad_y_geometria_invalida_sin_exponer_proveedor(self, abrir):
        for tramos in (None, [], [{"polyline": {"encodedPolyline": "????"}}], [None, {}],
                       [{"polyline": {"encodedPolyline": "secreto-no-valido"}}, {}],
                       [{"polyline": {"encodedPolyline": ""}}, {"polyline": {"encodedPolyline": "????"}}]):
            with self.subTest(tramos=tramos):
                abrir.return_value.__enter__.return_value.read.return_value = self._cuerpo(tramos)
                with self.assertRaises(ErrorProveedorGoogle) as recibido:
                    calcular_ruta_google(self.origen, self.destinos)
                self.assertEqual(str(recibido.exception), "RESPUESTA_INVALIDA")

    @patch("apps.rutas.proveedor_google.urlopen")
    def test_leg_vacio_solo_se_admite_si_origen_y_destino_son_iguales(self, abrir):
        abrir.return_value.__enter__.return_value.read.return_value = self._cuerpo([{}, {"polyline": {"encodedPolyline": "????"}}])
        resultado = calcular_ruta_google(self.origen, [self.origen, self.destinos[1]])
        self.assertEqual(resultado["polilineas_tramos"], ["", "????"])
