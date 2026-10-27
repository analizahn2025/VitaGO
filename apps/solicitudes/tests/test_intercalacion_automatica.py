"""Paquetes recogidos en espera y próximas paradas sin selección del motorista."""

from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.exceptions import ValidationError

from apps.evidencias.models import EvidenciaSolicitud
from apps.rutas.models import VersionRuta
from apps.rutas.servicios import sincronizar_ruta
from apps.seguimiento.models import RegistroUbicacion
from apps.solicitudes.models import EventoSolicitud, Solicitud
from apps.solicitudes.servicios import cambiar_estado_solicitud
from apps.solicitudes.tests import test_flujo_automatico as datos
from apps.ubicaciones.models import Ubicacion


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasIntercalacionAutomatica(TestCase):
    setUpTestData = classmethod(datos.PruebasFlujoAutomatico.setUpTestData.__func__)
    _archivo_png = datos.PruebasFlujoAutomatico._archivo_png
    _gps = datos.PruebasFlujoAutomatico._gps
    _leer = datos.PruebasFlujoAutomatico._leer
    _subir_foto = datos.PruebasFlujoAutomatico._subir_foto
    _registrar = datos.PruebasFlujoAutomatico._registrar
    _transicion = datos.PruebasFlujoAutomatico._transicion
    _estado = datos.PruebasFlujoAutomatico._estado
    _segunda = datos.PruebasFlujoAutomatico._segunda
    _activar = datos.PruebasFlujoAutomatico._activar

    def setUp(self):
        datos.PruebasFlujoAutomatico.setUp(self)
        # Puntos sintéticos: A recoge .001 y entrega .100; B recoge .002 y entrega .003.
        Ubicacion.objects.filter(pk=self.origen.pk).update(latitud="0", longitud=".001")
        Ubicacion.objects.filter(pk=self.destino.pk).update(latitud="0", longitud=".100")
        self.origen.refresh_from_db()
        self.destino.refresh_from_db()
        RegistroUbicacion.objects.filter(pk=self.gps.pk).update(latitud="0", longitud=".001")
        self._estado("AT_PICKUP")
        self.segunda = self._segunda()
        ubicaciones = [Ubicacion.objects.create(
            nombre=f"Parada sintética {longitud}", tipo_ubicacion=self.origen.tipo_ubicacion,
            origen=self.origen.origen, pais=self.empresa.pais, direccion="Solo pruebas",
            latitud="0", longitud=longitud,
        ) for longitud in (".002", ".003")]
        Solicitud.objects.filter(pk=self.segunda.pk).update(origen=ubicaciones[0], destino=ubicaciones[1])
        sincronizar_ruta(self.repartidor, VersionRuta.Motivo.ASIGNACION)

    def _recoger_primera(self):
        with self.captureOnCommitCallbacks(execute=True):
            respuesta = self._subir_foto()
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        self.solicitud.refresh_from_db()
        self.segunda.refresh_from_db()
        return respuesta

    def test_foto_deja_paquete_recogido_y_activa_recoleccion_cercana(self):
        respuesta = self._recoger_primera()
        self.assertEqual(respuesta.data["estado_solicitud"], "PICKED_UP")
        self.assertEqual(self.solicitud.estado, "PICKED_UP")
        self.assertEqual(self.segunda.estado, "GOING_TO_PICKUP")
        self.assertIsNotNone(self.solicitud.recolectada_en)
        self.assertEqual(EvidenciaSolicitud.objects.filter(solicitud=self.solicitud).count(), 1)
        flujo = self._leer()["flujo_actual"]
        self.assertEqual((flujo["solicitud_id"], flujo["tipo_parada"]), (str(self.segunda.pk), "RECOLECCION"))
        self.assertFalse(flujo["permite_elegir_etapa"])
        self.assertFalse(flujo["requiere_aceptacion"])

    def test_flujo_completo_entrega_b_antes_de_a_con_gps_y_fotos(self):
        self._recoger_primera()
        primera = self.solicitud
        self.solicitud = self.segunda
        self.origen, self.destino = self.segunda.origen, self.segunda.destino
        self._transicion("AT_PICKUP")  # Detector real con permanencia GPS de la fixture.
        with self.captureOnCommitCallbacks(execute=True):
            self._registrar("FOTO_RECOLECCION")
        self.solicitud.refresh_from_db()
        primera.refresh_from_db()
        self.assertEqual((primera.estado, self.solicitud.estado), ("PICKED_UP", "IN_TRANSIT"))
        self.assertEqual(self._leer()["flujo_actual"]["solicitud_id"], str(self.segunda.pk))
        self._transicion("AT_DESTINATION")
        with self.captureOnCommitCallbacks(execute=True):
            self._registrar("FOTO_ENTREGA")
        primera.refresh_from_db()
        self.solicitud.refresh_from_db()
        self.assertEqual((self.solicitud.estado, primera.estado), ("DELIVERED", "IN_TRANSIT"))
        self.solicitud = primera
        self.origen, self.destino = primera.origen, primera.destino
        self._transicion("AT_DESTINATION")
        with self.captureOnCommitCallbacks(execute=True):
            self._registrar("FOTO_ENTREGA")
        self.assertEqual(self._leer()["flujo_actual"]["pantalla"], "SIN_SERVICIOS")
        self.assertEqual(Solicitud.objects.filter(estado="DELIVERED").count(), 2)
        self.assertEqual(EvidenciaSolicitud.objects.count(), 4)

    def test_no_puede_elegir_entregar_a_antes_de_la_parada_b(self):
        self._recoger_primera()
        with self.assertRaises(ValidationError):
            cambiar_estado_solicitud(self.usuario_repartidor, self.solicitud.pk, {"estado_destino": "IN_TRANSIT"})
        with override_settings(LLEGADAS_AUTOMATICAS_HABILITADAS=False):
            Solicitud.objects.filter(pk=self.solicitud.pk).update(estado="IN_TRANSIT")
            with self.assertRaises(ValidationError):
                cambiar_estado_solicitud(self.usuario_repartidor, self.solicitud.pk, {"estado_destino": "AT_DESTINATION"})

    def test_repetir_activacion_no_duplica_eventos_de_b(self):
        self._recoger_primera()
        eventos = EventoSolicitud.objects.count()
        versiones = VersionRuta.objects.count()
        for _ in range(3):
            self.assertIsNone(self._activar())
        self.assertEqual(EventoSolicitud.objects.count(), eventos)
        self.assertEqual(VersionRuta.objects.count(), versiones)

    def test_prioritario_recogido_no_se_intercala(self):
        Solicitud.objects.filter(pk=self.solicitud.pk).update(prioridad="PRIORITY")
        self._recoger_primera()
        self.assertEqual(self.solicitud.estado, "IN_TRANSIT")
        self.assertEqual(self.segunda.estado, "ASSIGNED")
        self.assertEqual(self._leer()["flujo_actual"]["solicitud_id"], str(self.solicitud.pk))

    def test_fallo_al_guardar_recogida_revierte_foto_y_orden(self):
        orden = self._leer()["paradas"]
        with patch("apps.rutas.servicios.sincronizar_ruta", side_effect=RuntimeError("Fallo de versión")):
            with self.assertRaisesMessage(RuntimeError, "Fallo de versión"):
                self._registrar("FOTO_RECOLECCION")
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, "AT_PICKUP")
        self.assertFalse(EvidenciaSolicitud.objects.exists())
        self.assertEqual(self._leer()["paradas"], orden)

    def test_recupera_activacion_tras_fallo_posterior_al_commit(self):
        with patch("apps.solicitudes.flujo_automatico.activar_siguiente_servicio", side_effect=RuntimeError("Fallo temporal")), \
                self.assertLogs("vitago.api", level="ERROR"):
            self._recoger_primera()
        self.segunda.refresh_from_db()
        self.assertEqual(self.segunda.estado, "ASSIGNED")
        self.assertEqual(self._activar().pk, self.segunda.pk)
        self.assertEqual(self._leer()["flujo_actual"]["tipo_parada"], "RECOLECCION")

    def test_foto_repetida_no_recoge_ni_entrega_dos_veces(self):
        self._recoger_primera()
        eventos = EventoSolicitud.objects.count()
        respuesta = self._subir_foto()
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("tipo", respuesta.data)
        self.assertEqual(EventoSolicitud.objects.count(), eventos)
        self.assertEqual(EvidenciaSolicitud.objects.count(), 1)
