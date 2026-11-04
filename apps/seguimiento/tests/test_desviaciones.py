from datetime import timedelta
from unittest.mock import patch

from django.db import transaction
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.notificaciones.models import NotificacionUsuario
from apps.rutas.models import CalculoRutaVial, VersionRuta
from apps.rutas.ruta_vial import firma_paradas
from apps.rutas.selectores import obtener_paradas_operativas
from apps.rutas.servicios import sincronizar_ruta
from apps.seguimiento.desviaciones import detectar_desviacion
from apps.seguimiento.geometria import decodificar_polilinea, distancia_a_polilinea_metros
from apps.seguimiento.models import DesviacionRuta, RegistroUbicacion
from apps.seguimiento.tests import test_llegadas as datos
from apps.solicitudes.models import EventoSolicitud
from rest_framework.test import APIClient


def codificar(puntos):
    resultado, anterior = [], (0, 0)
    for punto in puntos:
        actual = tuple(round(float(c)*100000) for c in punto)
        for valor, previo in zip(actual, anterior):
            delta = valor - previo
            numero = ~(delta << 1) if delta < 0 else delta << 1
            while numero >= 32:
                resultado.append(chr(((numero & 31) | 32)+63))
                numero >>= 5
            resultado.append(chr(numero+63))
        anterior = actual
    return "".join(resultado)


class PruebasGeometriaDesvios(SimpleTestCase):
    def test_distancia_se_mide_al_segmento_y_no_solo_a_sus_vertices(self):
        self.assertLess(distancia_a_polilinea_metros(0.0001, 0.5, [(0,0),(0,1)]), 12)
        self.assertGreater(distancia_a_polilinea_metros(0.01, 0.5, [(0,0),(0,1)]), 1000)

    def test_polilinea_sintetica_y_entrada_malformada(self):
        puntos=[(14.0,-87.0),(14.1,-87.0)]
        self.assertEqual(decodificar_polilinea(codificar(puntos)), puntos)
        for texto in ("", "~", "~~~~~~~", "!", None):
            self.assertEqual(decodificar_polilinea(texto), [])


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL", DESVIACIONES_AUTOMATICAS_HABILITADAS=True)
class PruebasDesviacionesRuta(TestCase):
    setUpTestData = classmethod(datos.PruebasLlegadasAutomaticas.setUpTestData.__func__)
    _preparar_estado = datos.PruebasLlegadasAutomaticas._preparar_estado
    _punto = datos.PruebasLlegadasAutomaticas._punto

    def setUp(self):
        datos.PruebasLlegadasAutomaticas.setUp(self)
        self.cliente = APIClient()
        EventoSolicitud.objects.filter(solicitud=self.solicitud).update(creado_en=self.ahora-timedelta(minutes=5))
        with transaction.atomic():
            self.ruta = sincronizar_ruta(self.repartidor, VersionRuta.Motivo.INICIAL, jornada=self.jornada)
        self.firma = firma_paradas(obtener_paradas_operativas(self.repartidor))
        self.lat, self.lng = float(self.origen.latitud), float(self.origen.longitud)
        linea=codificar([(self.lat-0.01,self.lng),(self.lat+0.01,self.lng)])
        from uuid import uuid4
        self.calculo = CalculoRutaVial.objects.create(version=self.ruta.versiones.first(), estado="CALCULADA", intentos=1,
            token_intento=uuid4(), iniciada_en=self.ahora-timedelta(minutes=4), calculada_en=self.ahora-timedelta(minutes=4),
            expira_en=self.ahora+timedelta(hours=1), origen_gps={"latitud": str(self.lat-0.01), "longitud": str(self.lng)},
            paradas_calculadas=self.firma, polilinea_codificada=linea, polilineas_tramos=[linea]*len(self.firma))

    def _puntos(self, tiempos=(70,40,10), *, lejos=True, precision=8):
        for segundos in tiempos:
            punto=self._punto(segundos)
            RegistroUbicacion.objects.filter(pk=punto.pk).update(longitud=str(round(self.lng+(0.005 if lejos else 0),6)), precision_metros=precision)

    def _detectar(self, usuario=None):
        with patch("apps.seguimiento.desviaciones.timezone.now", return_value=self.ahora):
            return detectar_desviacion(usuario or self.usuario_repartidor, self.repartidor.pk, self.jornada.pk)

    def test_desvio_sostenido_notifica_una_vez_a_motorista_y_administrador(self):
        self._puntos()
        aviso=self._detectar()
        self.assertIsNotNone(aviso)
        self.assertEqual(DesviacionRuta.objects.count(),1)
        avisos=NotificacionUsuario.objects.filter(tipo="DESVIACION_RUTA")
        self.assertEqual(set(avisos.values_list("usuario_id",flat=True)), {self.administrador.pk,self.usuario_repartidor.pk})
        self.assertEqual(self._detectar()["id"],aviso["id"])
        self.assertEqual(avisos.count(),2)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado,"GOING_TO_PICKUP")

    def test_un_punto_y_desvio_corto_no_crean_alerta(self):
        self._puntos((10,))
        self.assertIsNone(self._detectar())
        self._puntos((25,20))
        self.assertIsNone(self._detectar())
        self.assertFalse(DesviacionRuta.objects.exists())

    def test_mala_precision_y_puntos_ausentes_rompen_racha(self):
        self._puntos(precision=200)
        self.assertIsNone(self._detectar())
        RegistroUbicacion.objects.update(precision_metros=None)
        self.assertIsNone(self._detectar())

    def test_un_hueco_de_captura_no_se_interpreta_como_permanencia(self):
        self._puntos((100,60,10))
        self.assertIsNone(self._detectar())

    def test_recepcion_gps_dispara_el_detector_despues_del_commit(self):
        from apps.seguimiento.servicios import registrar_ubicaciones
        from uuid import uuid4
        registros = [{"id_cliente": uuid4(), "latitud": str(round(self.lat,6)), "longitud": str(round(self.lng+0.005,6)),
                      "precision_metros": "8.00", "registrada_en": self.ahora-timedelta(seconds=s)} for s in (70,40,10)]
        with patch("apps.seguimiento.desviaciones.timezone.now",return_value=self.ahora):
            with self.captureOnCommitCallbacks(execute=True):
                resultado=registrar_ubicaciones(self.usuario_repartidor,{"jornada_id":self.jornada.pk,"registros":registros})
        self.assertEqual(len(resultado["alertas_ruta"]),1)
        self.assertEqual(DesviacionRuta.objects.count(),1)

    def test_una_nueva_salida_despues_de_regresar_crea_otro_evento(self):
        self._puntos(); self._detectar()
        self.ahora+=timedelta(seconds=60)
        self._puntos((25,15,5),lejos=False); self._detectar()
        self.ahora+=timedelta(seconds=120)
        self._puntos(); self._detectar()
        self.assertEqual(DesviacionRuta.objects.count(),2)
        self.assertEqual(DesviacionRuta.objects.filter(finalizada_en__isnull=True).count(),1)
        self.assertEqual(NotificacionUsuario.objects.filter(tipo="DESVIACION_RUTA").count(),4)

    def test_estar_en_ruta_no_genera_aviso(self):
        self._puntos(lejos=False)
        self.assertIsNone(self._detectar())

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_tambien_detecta_desvio_con_rol_global_de_motorista(self):
        from apps.flota.models import Vehiculo
        from apps.repartidores.models import Repartidor
        from apps.usuarios.models import RolUsuario, Rol, Usuario
        Repartidor.objects.filter(pk=self.repartidor.pk).update(empresa=None)
        Usuario.objetos.filter(pk=self.usuario_repartidor.pk).update(empresa=None)
        Vehiculo.objects.filter(pk=self.repartidor.vehiculo_id).update(empresa=None)
        RolUsuario.objetos.filter(usuario=self.usuario_repartidor).update(
            activo=False, revocado_en=self.ahora, revocado_por=self.administrador)
        RolUsuario.objetos.create(usuario=self.usuario_repartidor, rol=Rol.objetos.get(codigo="REPARTIDOR_RED"), tipo_alcance="GLOBAL")
        self._puntos()
        self.assertIsNotNone(self._detectar())
        self.assertEqual(DesviacionRuta.objects.count(),1)

    def test_no_evalua_ruta_vencida_y_no_consulta_proveedor(self):
        self._puntos()
        self.calculo.expira_en=self.ahora-timedelta(seconds=1)
        self.calculo.save(update_fields=("expira_en",))
        self.assertIsNone(self._detectar())

    def test_no_evalua_gps_antiguo_ni_jornada_cerrada(self):
        self._puntos((180,150,120))
        self.assertIsNone(self._detectar())
        self.jornada.estado="FINALIZADA"
        self.jornada.finalizada_en=self.ahora
        self.jornada.save()
        self.assertIsNone(self._detectar())

    def test_regreso_estable_cierra_aviso_sin_duplicar_notificaciones(self):
        self._puntos()
        self.assertIsNotNone(self._detectar())
        self.ahora+=timedelta(seconds=60)
        self._puntos((25,15,5),lejos=False)
        aviso=self._detectar()
        self.assertIsNotNone(aviso["finalizada_en"])
        self.assertEqual(DesviacionRuta.objects.get().motivo_cierre,"REGRESO_RUTA")
        self.assertEqual(NotificacionUsuario.objects.filter(tipo="DESVIACION_RUTA").count(),2)

    def test_otro_usuario_no_puede_disparar_alertas_del_motorista(self):
        self._puntos()
        self.assertIsNone(self._detectar(self.solicitante))
        self.assertFalse(DesviacionRuta.objects.exists())

    def test_cambio_etapa_cierra_alerta_y_get_la_recupera_sin_escrituras(self):
        self._puntos()
        self._detectar()
        self.cliente.force_authenticate(self.usuario_repartidor)
        respuesta=self.cliente.get(reverse("rutas:mi-ruta"))
        self.assertEqual(respuesta.status_code,200)
        self.assertEqual(respuesta.data["alerta_desviacion"]["id"],str(DesviacionRuta.objects.get().pk))
        self.solicitud.estado="AT_PICKUP"
        self.solicitud.save()
        with transaction.atomic():
            sincronizar_ruta(self.repartidor,VersionRuta.Motivo.CAMBIO_ESTADO)
        self.assertIsNotNone(DesviacionRuta.objects.get().finalizada_en)
