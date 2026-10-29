"""Las operaciones que compiten por un motorista comparten el bloqueo de fila."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import threading
from unittest import skipUnless
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings
from rest_framework.exceptions import ValidationError

from apps.jornadas.models import AlmuerzoJornada, JornadaRepartidor
from apps.jornadas.servicios import cambiar_almuerzo, iniciar_jornada
from apps.jornadas.tests import test_jornadas as datos
from apps.solicitudes.models import Solicitud
from apps.solicitudes.servicios import asignar_solicitud_manualmente
from apps.usuarios.models import Usuario


@skipUnless(connection.vendor == "postgresql", "Requiere PostgreSQL y bloqueos reales.")
@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasConcurrenciaAlmuerzo(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        datos.PruebasJornadas.setUpTestData.__func__(type(self))
        self.repartidor = self.repartidores[0]
        reloj = patch("django.utils.timezone.now", return_value=datetime(2026, 10, 29, 12, tzinfo=ZoneInfo("America/Tegucigalpa")))
        reloj.start()
        self.addCleanup(reloj.stop)

    def test_dos_inicios_simultaneos_crean_una_sola_jornada(self):
        salida = threading.Barrier(2)

        def iniciar():
            close_old_connections()
            try:
                usuario = Usuario.objetos.get(pk=self.repartidor.usuario_id)
                salida.wait(5)
                try:
                    iniciar_jornada(usuario, {})
                    return "CREADA"
                except ValidationError:
                    return "RECHAZADA"
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as grupo:
            futuros = [grupo.submit(iniciar) for _ in range(2)]
            resultados = [futuro.result(15) for futuro in futuros]
        self.assertCountEqual(resultados, ["CREADA", "RECHAZADA"])
        self.assertEqual(JornadaRepartidor.objects.filter(repartidor=self.repartidor).count(), 1)

    def _competir(self, primero_almuerzo):
        jornada = iniciar_jornada(self.repartidor.usuario, {})
        solicitud = Solicitud.objects.create(numero="CARRERA-ALMUERZO", empresa=self.empresa,
            solicitada_por=self.administrador, origen=self.origen, destino=self.destino,
            prioridad="NORMAL", cantidad_tubos=1)
        tomado, liberar, segundo_iniciado = threading.Event(), threading.Event(), threading.Event()

        def ejecutar(almuerzo, primero):
            close_old_connections()
            try:
                with transaction.atomic():
                    if not primero:
                        segundo_iniciado.set()
                    try:
                        if almuerzo:
                            cambiar_almuerzo(self.repartidor.usuario, jornada.pk, iniciar=True)
                        else:
                            asignar_solicitud_manualmente(self.administrador, solicitud.pk, {"repartidor_id": self.repartidor.pk})
                    except ValidationError as error:
                        return error.detail
                    if primero:
                        tomado.set()
                        if not liberar.wait(10):
                            raise AssertionError("La prueba no liberó la primera operación.")
                return "OK"
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as grupo:
            primero = grupo.submit(ejecutar, primero_almuerzo, True)
            try:
                self.assertTrue(tomado.wait(5))
                segundo = grupo.submit(ejecutar, not primero_almuerzo, False)
                self.assertTrue(segundo_iniciado.wait(5))
                self.assertFalse(segundo.done())
            finally:
                liberar.set()
            self.assertEqual(primero.result(10), "OK")
            self.assertIn("repartidor_id" if primero_almuerzo else "almuerzo", segundo.result(10))
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.repartidor_asignado_id is None, primero_almuerzo)
        self.assertEqual(AlmuerzoJornada.objects.filter(finalizada_en__isnull=True).exists(), primero_almuerzo)

    def test_almuerzo_confirmado_impide_asignacion_que_estaba_esperando(self):
        self._competir(True)

    def test_asignacion_confirmada_impide_almuerzo_que_estaba_esperando(self):
        self._competir(False)
