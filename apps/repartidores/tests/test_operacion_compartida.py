"""Contrato del guardado común sin alterar permisos ni políticas operativas."""

from types import SimpleNamespace
from unittest.mock import patch

from django.db import transaction
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.exceptions import ValidationError

from apps.repartidores.capacidad import sincronizar_capacidad_repartidor
from apps.repartidores.models import HistorialEstadoRepartidor
from apps.repartidores.operacion import guardar_cambio_operativo, registrar_operacion_repartidor
from apps.repartidores.servicios import actualizar_operacion_repartidor
from apps.solicitudes.models import Solicitud
from apps.solicitudes.opciones import ESTADOS_SOLICITUD_ACTIVOS, EstadoSolicitud
from apps.solicitudes.tests import test_asignaciones as datos_asignaciones


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasOperacionCompartida(TestCase):
    setUpTestData = classmethod(datos_asignaciones.PruebasAsignacionesSolicitud.setUpTestData.__func__)

    def setUp(self):
        self.repartidor = self.repartidores[0]

    def _solicitud(self, estado=EstadoSolicitud.ASIGNADA):
        return Solicitud.objects.create(
            cantidad_tubos=1,
            numero=f"OPERACION-{Solicitud.objects.count()}", empresa=self.empresa,
            solicitada_por=self.administrador, repartidor_asignado=self.repartidor,
            prioridad="NORMAL", origen=self.origen, destino=self.destino, estado=estado,
        )

    def test_sin_cambios_no_guarda_ni_actualiza_fecha_ni_duplica_historial(self):
        fecha = self.repartidor.actualizado_en
        with self.assertNumQueries(1):
            cantidad = registrar_operacion_repartidor(self.repartidor, self.administrador, motivo="Sin cambios")
        self.assertEqual(cantidad, 0)
        self.repartidor.refresh_from_db()
        self.assertEqual(self.repartidor.actualizado_en, fecha)
        self.assertFalse(HistorialEstadoRepartidor.objects.exists())

    def test_estado_y_capacidad_cambian_juntos_con_un_solo_historial(self):
        for _ in range(3):
            self._solicitud()
        cantidad = registrar_operacion_repartidor(self.repartidor, self.administrador,
            estado_nuevo="ON_ROUTE", motivo="Inicio de operación")
        self.assertEqual(cantidad, 3)
        self.repartidor.refresh_from_db()
        self.assertEqual((self.repartidor.estado_operativo, self.repartidor.capacidad), ("ON_ROUTE", "AVAILABLE_SPACE"))
        historial = HistorialEstadoRepartidor.objects.get()
        self.assertEqual((historial.estado_anterior, historial.estado_nuevo), ("AVAILABLE", "ON_ROUTE"))
        self.assertEqual((historial.capacidad_anterior, historial.capacidad_nueva), ("EMPTY", "AVAILABLE_SPACE"))
        self.assertEqual((historial.realizado_por_id, historial.motivo), (self.administrador.pk, "Inicio de operación"))

    def test_carga_solo_cuenta_estados_activos_y_conserva_limite_de_cinco(self):
        for estado in ESTADOS_SOLICITUD_ACTIVOS:
            self._solicitud(estado)
        for estado in ("PENDING", "DELIVERED", "CANCELLED", "PICKUP_FAILED", "DELIVERY_FAILED"):
            self._solicitud(estado)
        cantidad = sincronizar_capacidad_repartidor(self.repartidor, self.administrador, "Carga calculada")
        self.assertEqual(cantidad, len(ESTADOS_SOLICITUD_ACTIVOS))
        self.assertEqual(self.repartidor.capacidad, "FULL")

    def test_solo_capacidad_no_levanta_pausa_y_no_reescribe_estado(self):
        self._solicitud()
        self.repartidor.estado_operativo = "PAUSED"
        self.repartidor.save()
        with patch.object(self.repartidor, "save", wraps=self.repartidor.save) as guardar:
            self.assertEqual(sincronizar_capacidad_repartidor(self.repartidor, self.administrador, "Recalcular"), 1)
        guardar.assert_called_once_with(update_fields=("capacidad", "actualizado_en"))
        historial = HistorialEstadoRepartidor.objects.get()
        self.assertEqual((historial.estado_anterior, historial.estado_nuevo), ("PAUSED", "PAUSED"))
        self.assertEqual(self.repartidor.estado_operativo, "PAUSED")

    def test_solo_estado_no_reescribe_capacidad(self):
        with patch.object(self.repartidor, "save", wraps=self.repartidor.save) as guardar:
            registrar_operacion_repartidor(self.repartidor, self.administrador,
                estado_nuevo="OFFLINE", motivo="Cierre de jornada")
        guardar.assert_called_once_with(update_fields=("estado_operativo", "actualizado_en"))
        self.assertEqual(self.repartidor.capacidad, "EMPTY")

    def test_sistema_conserva_autor_nulo_y_motivo_de_auditoria(self):
        registrar_operacion_repartidor(self.repartidor, None,
            estado_nuevo="OFFLINE", motivo="Fin del día operativo.")
        historial = HistorialEstadoRepartidor.objects.get()
        self.assertIsNone(historial.realizado_por_id)
        self.assertEqual(historial.motivo, "Fin del día operativo.")

    def test_error_de_historial_revierte_el_cambio_dentro_de_la_transaccion(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                with patch("apps.repartidores.operacion.HistorialEstadoRepartidor.objects.create", side_effect=RuntimeError("Fallo simulado")):
                    registrar_operacion_repartidor(self.repartidor, self.administrador,
                        estado_nuevo="PAUSED", motivo="No debe persistir")
        self.repartidor.refresh_from_db()
        self.assertEqual((self.repartidor.estado_operativo, self.repartidor.capacidad), ("AVAILABLE", "EMPTY"))
        self.assertFalse(HistorialEstadoRepartidor.objects.exists())

    def test_api_operativa_conserva_error_de_no_cambios_efectivos(self):
        with self.assertRaises(ValidationError) as rechazo:
            actualizar_operacion_repartidor(self.repartidor.usuario, self.repartidor.pk,
                {"estado_operativo": "AVAILABLE"})
        self.assertEqual(str(rechazo.exception.detail[0]), "La operación no contiene cambios efectivos.")
        self.assertFalse(HistorialEstadoRepartidor.objects.exists())

    def test_funcion_compartida_no_introduce_condicionales_por_despliegue(self):
        self._solicitud()
        for modo, estado in (("CORPORATIVO", "PAUSED"), ("EXTERNO", "OFFLINE")):
            with self.subTest(modo=modo), override_settings(MODO_APLICACION=modo):
                self.assertEqual(registrar_operacion_repartidor(self.repartidor, self.administrador,
                    estado_nuevo=estado, motivo="Reutilización de persistencia"), 1)
                self.assertEqual(self.repartidor.capacidad, "AVAILABLE_SPACE")


class PruebasContratoTransaccionalOperacion(SimpleTestCase):
    def test_escritura_fuera_de_transaccion_se_rechaza_antes_de_consultar(self):
        with patch("apps.repartidores.operacion.transaction.get_connection", return_value=SimpleNamespace(in_atomic_block=False)):
            with self.assertRaises(RuntimeError):
                registrar_operacion_repartidor(object(), None, motivo="Sin transacción")
            with self.assertRaises(RuntimeError):
                guardar_cambio_operativo(object(), None, estado_nuevo="OFFLINE", capacidad_nueva="EMPTY", motivo="Sin transacción")
