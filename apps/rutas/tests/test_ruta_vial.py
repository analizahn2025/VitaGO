"""Pruebas sin red ni credenciales reales para navegación y presupuesto."""

import json
from datetime import timedelta
from decimal import Decimal
from io import BytesIO, StringIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.jornadas.models import JornadaRepartidor
from apps.rutas.models import CalculoRutaVial, ConsumoRutasGoogle, VersionRuta
from apps.rutas.proveedor_google import ErrorProveedorGoogle, calcular_ruta_google
from apps.rutas.servicios import sincronizar_ruta
from apps.rutas.tests.test_mi_ruta import PruebasMiRuta
from apps.seguimiento.models import RegistroUbicacion
from apps.solicitudes.models import Solicitud
from apps.solicitudes.opciones import EstadoSolicitud, ModalidadSolicitud, PrioridadSolicitud
from apps.usuarios.models import PermisoRol


RESULTADO = {"polilinea_codificada": "_p~iF~ps|U_ulLnnqC_mqNvxq`@",
             "distancia_estimada_metros": 1800, "duracion_estimada_segundos": 250.5}


@override_settings(MODO_APLICACION="CORPORATIVO", HABILITAR_RUTAS_GOOGLE=True,
                   CLAVE_API_GOOGLE_MAPS="solo-pruebas", RUTAS_GOOGLE_LIMITE_DIARIO=50,
                   RUTAS_GOOGLE_LIMITE_MENSUAL=500, RUTAS_GOOGLE_INTENTOS_POR_VERSION=2)
class PruebasRutaVial(TestCase):
    setUpTestData = classmethod(PruebasMiRuta.setUpTestData.__func__)
    motorista = PruebasMiRuta.motorista
    _crear_solicitud = PruebasMiRuta._crear_solicitud
    _cliente = PruebasMiRuta._cliente

    def setUp(self):
        self.solicitud = self._crear_solicitud("SOL-VIAL-1")
        self.ruta = sincronizar_ruta(self.motorista, VersionRuta.Motivo.ASIGNACION)
        self.jornada = JornadaRepartidor.objects.create(repartidor=self.motorista)
        self.punto = RegistroUbicacion.objects.create(
            id_cliente=uuid4(), repartidor=self.motorista, jornada=self.jornada,
            latitud="14.072000", longitud="-87.192000", precision_metros="5.00",
            registrada_en=timezone.now(),
        )
        self.cliente = self._cliente(self.motorista.usuario)
        self.url = reverse("rutas:calcular-mi-ruta")

    def calcular(self, **datos):
        return self.cliente.post(self.url, {"version_actual": 1, **datos}, format="json")

    @patch("apps.rutas.ruta_vial.calcular_ruta_google", return_value=RESULTADO)
    def test_lectura_sin_red_y_navegacion_sin_clave(self, proveedor):
        with override_settings(HABILITAR_RUTAS_GOOGLE=False, CLAVE_API_GOOGLE_MAPS=""):
            respuesta = self.cliente.get(reverse("rutas:mi-ruta"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data["ruta_vial"]["estado"], "NO_CONFIGURADA")
        enlace = respuesta.data["navegacion"]
        parametros = parse_qs(urlparse(enlace["url"]).query)
        self.assertEqual(parametros["travelmode"], ["two-wheeler"])
        self.assertEqual(parametros["destination"], ["14.072300,-87.192100"])
        self.assertNotIn("origin", parametros)
        self.assertFalse(enlace["requiere_clave_api"])
        proveedor.assert_not_called()
        self.assertFalse(CalculoRutaVial.objects.exists())
        self.assertEqual(self.ruta.versiones.count(), 1)

    @patch("apps.rutas.ruta_vial.calcular_ruta_google", return_value=RESULTADO)
    def test_calculo_y_repeticion_no_generan_cargo_extra(self, proveedor):
        primera = self.calcular()
        self.assertEqual(primera.status_code, 200, primera.data)
        self.assertTrue(primera.data["metricas_en_respuesta"])
        self.assertEqual(primera.data["duracion_estimada_segundos"], 250.5)
        self.assertEqual(primera.data["atribucion"], "Google Maps")
        segunda = self.calcular()
        self.assertEqual(segunda.status_code, 200)
        self.assertFalse(segunda.data["metricas_en_respuesta"])
        self.assertIsNone(segunda.data["distancia_estimada_metros"])
        self.assertEqual(segunda.data["polilinea_codificada"], RESULTADO["polilinea_codificada"])
        proveedor.assert_called_once()
        self.assertEqual(list(ConsumoRutasGoogle.objects.values_list("intentos_reservados", flat=True)), [1, 1])
        calculo = CalculoRutaVial.objects.get()
        self.assertEqual(calculo.origen_gps["latitud"], "14.072000")
        self.assertNotIn("distancia_estimada_metros", calculo.origen_gps)
        self.assertFalse(hasattr(calculo, "duracion_estimada_segundos"))

    @patch("apps.rutas.ruta_vial.calcular_ruta_google", return_value=RESULTADO)
    def test_avanzar_paradas_reutiliza_trazado_inicial(self, proveedor):
        self.assertEqual(self.calcular().status_code, 200)
        Solicitud.objects.filter(pk=self.solicitud.pk).update(estado=EstadoSolicitud.RECOLECTADA)
        sincronizar_ruta(self.motorista, VersionRuta.Motivo.CAMBIO_ESTADO)
        respuesta = self.cliente.get(reverse("rutas:mi-ruta"))
        self.assertTrue(respuesta.data["ruta_calculada"])
        self.assertTrue(respuesta.data["ruta_vial"]["incluye_tramos_completados"])
        self.assertEqual(respuesta.data["ruta_vial"]["version_calculada"], 1)
        self.assertEqual(respuesta.data["version_actual"], 2)
        self.assertEqual(self.calcular(version_actual=2).status_code, 200)
        proveedor.assert_called_once()

    @patch("apps.rutas.ruta_vial.calcular_ruta_google", return_value=RESULTADO)
    def test_nueva_asignacion_requiere_version_actual_y_otro_calculo_explicito(self, proveedor):
        self.calcular()
        self._crear_solicitud("SOL-VIAL-2", minutos_atras=0)
        sincronizar_ruta(self.motorista, VersionRuta.Motivo.ASIGNACION)
        lectura = self.cliente.get(reverse("rutas:mi-ruta"))
        self.assertFalse(lectura.data["ruta_calculada"])
        vieja = self.calcular()
        self.assertEqual(vieja.status_code, 409)
        self.assertEqual(vieja.data["codigo"], "VERSION_DESACTUALIZADA")
        self.assertEqual(self.calcular(version_actual=2).status_code, 200)
        self.assertEqual(proveedor.call_count, 2)

    @patch("apps.rutas.ruta_vial.calcular_ruta_google", return_value=RESULTADO)
    def test_coordenada_editada_publica_version_nueva_sin_cargo(self, proveedor):
        self.destino.latitud = Decimal("14.083000")
        self.destino.save(update_fields=("latitud", "actualizado_en"))
        respuesta = self.calcular()
        self.assertEqual(respuesta.status_code, 409)
        self.assertEqual(self.cliente.get(reverse("rutas:mi-ruta")).data["version_actual"], 2)
        proveedor.assert_not_called()

    @patch("apps.rutas.ruta_vial.calcular_ruta_google", return_value=RESULTADO)
    def test_gps_obsoleto_no_reserva_presupuesto(self, proveedor):
        RegistroUbicacion.objects.filter(pk=self.punto.pk).update(registrada_en=timezone.now() - timedelta(minutes=10))
        respuesta = self.calcular()
        self.assertEqual(respuesta.status_code, 409)
        self.assertEqual(respuesta.data["codigo"], "GPS_NO_VIGENTE")
        self.assertFalse(ConsumoRutasGoogle.objects.exists())
        proveedor.assert_not_called()

    @patch("apps.rutas.ruta_vial.calcular_ruta_google", return_value=RESULTADO)
    def test_google_desactivado_no_llama_red(self, proveedor):
        with override_settings(HABILITAR_RUTAS_GOOGLE=False):
            respuesta = self.calcular()
        self.assertEqual(respuesta.status_code, 503)
        self.assertEqual(respuesta.data["codigo"], "GOOGLE_NO_CONFIGURADO")
        proveedor.assert_not_called()

    @patch("apps.rutas.ruta_vial.calcular_ruta_google", return_value=RESULTADO)
    def test_presupuesto_mensual_exhausto_no_consume_diario(self, proveedor):
        ConsumoRutasGoogle.objects.create(periodo="MENSUAL", fecha=timezone.localdate().replace(day=1), intentos_reservados=500)
        respuesta = self.calcular()
        self.assertEqual(respuesta.status_code, 429)
        self.assertEqual(respuesta.data["codigo"], "LIMITE_CONSUMO")
        self.assertFalse(ConsumoRutasGoogle.objects.filter(periodo="DIARIO").exists())
        self.assertFalse(CalculoRutaVial.objects.exists())
        proveedor.assert_not_called()

    @patch("apps.rutas.ruta_vial.calcular_ruta_google", side_effect=ErrorProveedorGoogle("CONEXION_GOOGLE", True))
    def test_fallo_reintento_explicito_y_limite(self, proveedor):
        self.assertEqual(self.calcular().status_code, 503)
        self.assertEqual(self.calcular().data["codigo"], "REINTENTO_EXPLICITO_REQUERIDO")
        self.assertEqual(self.calcular(reintentar=True).data["codigo"], "ESPERAR_REINTENTO")
        CalculoRutaVial.objects.update(reintento_desde=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.calcular(reintentar=True).status_code, 503)
        self.assertEqual(self.calcular(reintentar=True).data["codigo"], "LIMITE_INTENTOS")
        self.assertEqual(proveedor.call_count, 2)
        self.assertEqual(list(ConsumoRutasGoogle.objects.values_list("intentos_reservados", flat=True)), [2, 2])

    @patch("apps.rutas.ruta_vial.calcular_ruta_google", side_effect=ErrorProveedorGoogle("SIN_RUTA"))
    def test_fallo_permanente_no_reintenta(self, proveedor):
        self.assertEqual(self.calcular().status_code, 503)
        self.assertEqual(self.calcular(reintentar=True).data["codigo"], "FALLA_NO_REINTENTABLE")
        proveedor.assert_called_once()

    @patch("apps.rutas.ruta_vial.calcular_ruta_google", return_value=RESULTADO)
    def test_intento_en_curso_no_duplicado_y_recuperacion_explicita(self, proveedor):
        version = self.ruta.versiones.get()
        CalculoRutaVial.objects.create(version=version, estado="CALCULANDO", intentos=1,
            token_intento=uuid4(), iniciada_en=timezone.now())
        self.assertEqual(self.calcular().data["codigo"], "CALCULO_EN_CURSO")
        CalculoRutaVial.objects.update(iniciada_en=timezone.now() - timedelta(minutes=2))
        lectura = self.cliente.get(reverse("rutas:mi-ruta"))
        self.assertEqual(lectura.data["ruta_vial"]["estado"], "FALLIDA")
        self.assertEqual(lectura.data["ruta_vial"]["codigo_error"], "INTENTO_INTERRUPPIDO")
        self.assertEqual(CalculoRutaVial.objects.get().estado, "CALCULANDO")
        self.assertEqual(self.calcular().data["codigo"], "REINTENTO_EXPLICITO_REQUERIDO")
        self.assertEqual(self.calcular(reintentar=True).status_code, 200)
        proveedor.assert_called_once()

    @patch("apps.rutas.ruta_vial.calcular_ruta_google", return_value=RESULTADO)
    def test_vencimiento_no_recalcula_misma_version_y_limpieza_conserva_auditoria(self, proveedor):
        self.calcular()
        CalculoRutaVial.objects.update(expira_en=timezone.now() - timedelta(seconds=1))
        lectura = self.cliente.get(reverse("rutas:mi-ruta"))
        self.assertEqual(lectura.data["ruta_vial"]["estado"], "VENCIDA")
        self.assertIsNone(lectura.data["ruta_vial"]["polilinea_codificada"])
        # GET no escribe, la tarea de limpieza sí elimina contenido vencido.
        self.assertTrue(CalculoRutaVial.objects.get().polilinea_codificada)
        call_command("limpiar_rutas_google_vencidas", stdout=StringIO())
        self.assertEqual(CalculoRutaVial.objects.get().polilinea_codificada, "")
        self.assertEqual(self.calcular(reintentar=True).data["codigo"], "RUTA_VENCIDA")
        self.assertTrue(CalculoRutaVial.objects.get().paradas_calculadas)
        proveedor.assert_called_once()

    @patch("apps.rutas.ruta_vial.calcular_ruta_google")
    def test_cambio_durante_http_descarta_respuesta(self, proveedor):
        def responder(*args):
            self._crear_solicitud("SOL-DURANTE-HTTP", minutos_atras=0)
            sincronizar_ruta(self.motorista, VersionRuta.Motivo.ASIGNACION)
            return RESULTADO
        proveedor.side_effect = responder
        respuesta = self.calcular()
        self.assertEqual(respuesta.status_code, 409)
        calculo = CalculoRutaVial.objects.get()
        self.assertEqual(calculo.codigo_error, "ITINERARIO_CAMBIO")
        self.assertEqual(calculo.polilinea_codificada, "")
        self.assertEqual(calculo.estado, "FALLIDA")

    @patch("apps.rutas.ruta_vial.calcular_ruta_google", return_value=RESULTADO)
    def test_prioritario_recogido_no_incluye_paradas_normales(self, proveedor):
        prioritario = self._crear_solicitud("SOL-PRIORIDAD", prioridad=PrioridadSolicitud.PRIORITARIA, estado=EstadoSolicitud.RECOLECTADA)
        sincronizar_ruta(self.motorista, VersionRuta.Motivo.ASIGNACION)
        self.assertEqual(self.calcular(version_actual=2).status_code, 200)
        self.assertEqual(len(proveedor.call_args.args[1]), 1)
        self.assertEqual(CalculoRutaVial.objects.get().paradas_calculadas[0]["solicitud_id"], str(prioritario.id))

    @patch("apps.rutas.ruta_vial.calcular_ruta_google", return_value=RESULTADO)
    def test_especial_sin_mapa_ni_google(self, proveedor):
        Solicitud.objects.filter(pk=self.solicitud.pk).update(estado=EstadoSolicitud.CANCELADA)
        self._crear_solicitud("SOL-ESPECIAL", modalidad=ModalidadSolicitud.ESPECIAL)
        sincronizar_ruta(self.motorista, VersionRuta.Motivo.CAMBIO_ESTADO)
        lectura = self.cliente.get(reverse("rutas:mi-ruta"))
        self.assertIsNone(lectura.data["navegacion"])
        self.assertEqual(lectura.data["ruta_vial"]["estado"], "SOLO_KILOMETROS")
        self.assertEqual(self.calcular(version_actual=2).data["codigo"], "SIN_PARADAS_CARTOGRAFIABLES")
        proveedor.assert_not_called()

    @patch("apps.rutas.ruta_vial.calcular_ruta_google", return_value=RESULTADO)
    def test_validaciones_y_permiso_propietario(self, proveedor):
        self.assertEqual(APIClient().post(self.url, {"version_actual": 1}).status_code, 401)
        self.assertEqual(self.calcular(origen={"latitud": 0}).status_code, 400)
        self.assertEqual(self.cliente.post(self.url, {}, format="json").status_code, 400)
        PermisoRol.objetos.filter(permiso__codigo="ruta.calcular").update(activo=False)
        self.assertEqual(self.calcular().status_code, 403)
        proveedor.assert_not_called()

    @patch("apps.rutas.ruta_vial.calcular_ruta_google", return_value=RESULTADO)
    def test_otro_motorista_no_calcula_ruta_ajena(self, proveedor):
        respuesta = self._cliente(self.motoristas[1].usuario).post(self.url, {"version_actual": 1}, format="json")
        self.assertEqual(respuesta.status_code, 409)
        self.assertFalse(CalculoRutaVial.objects.exists())
        proveedor.assert_not_called()

    @patch("apps.rutas.ruta_vial.calcular_ruta_google", return_value=RESULTADO)
    def test_presupuesto_diario_exhausto(self, proveedor):
        ConsumoRutasGoogle.objects.create(periodo="DIARIO", fecha=timezone.localdate(), intentos_reservados=50)
        self.assertEqual(self.calcular().status_code, 429)
        self.assertFalse(CalculoRutaVial.objects.exists())
        proveedor.assert_not_called()

    @patch("apps.rutas.ruta_vial.calcular_ruta_google", return_value=RESULTADO)
    def test_coordenadas_repetidas_se_agrupan_sin_quitar_paradas(self, proveedor):
        Solicitud.objects.filter(pk=self.solicitud.pk).update(destino=self.origen)
        sincronizar_ruta(self.motorista, VersionRuta.Motivo.CAMBIO_ESTADO)
        self.assertEqual(self.calcular(version_actual=2).status_code, 200)
        self.assertEqual(len(proveedor.call_args.args[1]), 1)
        self.assertEqual(len(CalculoRutaVial.objects.get().paradas_calculadas), 2)

    @override_settings(MODO_APLICACION="EXTERNO")
    @patch("apps.rutas.ruta_vial.calcular_ruta_google", return_value=RESULTADO)
    def test_ruta_funciona_tambien_en_network(self, proveedor):
        self.assertEqual(self.calcular().status_code, 200)
        proveedor.assert_called_once()


@override_settings(HABILITAR_RUTAS_GOOGLE=True, CLAVE_API_GOOGLE_MAPS="clave-ficticia")
class PruebasProveedorGoogle(SimpleTestCase):
    origen = {"latitud": "14.07", "longitud": "-87.19"}
    destinos = [{"latitud": "14.08", "longitud": "-87.18"}]

    @patch("apps.rutas.proveedor_google.urlopen")
    def test_cuerpo_mascara_motocicleta_y_respuesta(self, abrir):
        abrir.return_value.__enter__.return_value.read.return_value = json.dumps({"routes": [{
            "distanceMeters": 1800, "duration": "250.5s", "polyline": {"encodedPolyline": RESULTADO["polilinea_codificada"]},
        }]}).encode()
        resultado = calcular_ruta_google(self.origen, self.destinos)
        self.assertEqual(resultado, RESULTADO)
        solicitud = abrir.call_args.args[0]
        cuerpo = json.loads(solicitud.data)
        self.assertEqual(cuerpo["travelMode"], "TWO_WHEELER")
        self.assertEqual(cuerpo["routingPreference"], "TRAFFIC_AWARE")
        self.assertFalse(cuerpo["optimizeWaypointOrder"])
        self.assertNotIn("*", solicitud.get_header("X-goog-fieldmask"))
        self.assertEqual(solicitud.get_header("X-goog-maps-solution-id"), "gmp_git_agentskills_v1")

    @patch("apps.rutas.proveedor_google.urlopen")
    def test_rechaza_html_json_invalido_y_datos_malformados(self, abrir):
        for contenido in (b"<html>error</html>", b"{}", b'{"routes":[{"distanceMeters":true}]}', b"[1]", b"x" * 1048577):
            with self.subTest(contenido=contenido[:60]):
                abrir.return_value.__enter__.return_value.read.return_value = contenido
                with self.assertRaises(ErrorProveedorGoogle):
                    calcular_ruta_google(self.origen, self.destinos)

    @patch("apps.rutas.proveedor_google.urlopen")
    def test_error_red_y_cuota_sin_exponer_datos(self, abrir):
        for error, codigo in ((URLError("secreto-remoto"), "CONEXION_GOOGLE"),
                              (HTTPError("url-privada", 429, "secreto-remoto", {}, BytesIO()), "CUOTA_GOOGLE")):
            abrir.side_effect = error
            with self.assertRaises(ErrorProveedorGoogle) as recibido:
                calcular_ruta_google(self.origen, self.destinos)
            self.assertEqual(str(recibido.exception), codigo)
            self.assertTrue(recibido.exception.reintentable)

    @patch("apps.rutas.proveedor_google.urlopen")
    def test_sin_clave_y_coordenada_invalida_no_envia(self, abrir):
        with override_settings(CLAVE_API_GOOGLE_MAPS=""):
            with self.assertRaises(ErrorProveedorGoogle):
                calcular_ruta_google(self.origen, self.destinos)
        with self.assertRaises(ErrorProveedorGoogle):
            calcular_ruta_google({"latitud": "nan", "longitud": "-87"}, self.destinos)
        abrir.assert_not_called()
