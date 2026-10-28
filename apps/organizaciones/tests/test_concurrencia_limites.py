"""Bloqueos reales: lectores compatibles y cambios que esperan la asignación."""

from concurrent.futures import ThreadPoolExecutor
import threading
import time
from unittest import skipUnless

from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings

from apps.geografia.models import Pais
from apps.organizaciones.limites import configurar_limites_empresa, configurar_limites_red
from apps.organizaciones.models import Empresa, LimitesMotoristasRed
from apps.repartidores.limites import obtener_limites_repartidor
from apps.repartidores.models import Repartidor
from apps.usuarios.models import Usuario


@skipUnless(connection.vendor == "postgresql", "Requiere PostgreSQL y bloqueos reales.")
class PruebasConcurrenciaLimites(TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        pais = Pais.objects.create(iso2="ZZ", iso3="ZZZ", nombre="Prueba", codigo_telefonico="+000", codigo_moneda="XXX", zona_horaria_predeterminada="UTC")
        self.empresa = Empresa.objects.create(nombre="Empresa de prueba", pais=pais)
        self.admin = Usuario.objetos.create(correo="admin@bloqueos.test", nombres="Admin", apellidos="Prueba", es_superusuario=True)
        self.motoristas = []
        for indice in range(2):
            usuario = Usuario.objetos.create(correo=f"motorista{indice}@bloqueos.test", nombres="Motorista", apellidos=str(indice))
            self.motoristas.append(Repartidor.objects.create(usuario=usuario, empresa=self.empresa))
        LimitesMotoristasRed.objects.get_or_create(pk=1)

    def _leer(self, identificador, adquirido, liberar, pids):
        close_old_connections()
        try:
            with transaction.atomic():
                r = Repartidor.objects.select_for_update().get(pk=identificador)
                limites = obtener_limites_repartidor(r, bloquear=True)
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids.append(cursor.fetchone()[0])
                adquirido.set()
                if not liberar.wait(10):
                    raise AssertionError("La prueba no liberó el lector.")
                return limites
        finally:
            connection.close()

    def test_dos_motoristas_pueden_leer_cupos_sin_serializar_toda_la_flota(self):
        for modo in ("CORPORATIVO", "EXTERNO"):
            with self.subTest(modo=modo), override_settings(MODO_APLICACION=modo):
                tomado_a, tomado_b, liberar = threading.Event(), threading.Event(), threading.Event()
                with ThreadPoolExecutor(max_workers=2) as grupo:
                    primero = grupo.submit(self._leer, self.motoristas[0].pk, tomado_a, liberar, [])
                    try:
                        self.assertTrue(tomado_a.wait(5))
                        segundo = grupo.submit(self._leer, self.motoristas[1].pk, tomado_b, liberar, [])
                        self.assertTrue(tomado_b.wait(5), "Los lectores de la configuración deben ser compatibles.")
                    finally:
                        liberar.set()
                    self.assertEqual(primero.result(5)["limite_tubos"], 20)
                    self.assertEqual(segundo.result(5)["limite_tubos"], 20)

    def _escribir(self, modo, iniciado, pids):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                pids.append(cursor.fetchone()[0])
            iniciado.set()
            if modo == "EXTERNO":
                return configurar_limites_red(self.admin, {"limite_tubos": 30}).limite_tubos_por_motorista
            return configurar_limites_empresa(self.admin, self.empresa.pk, {"limite_tubos": 30}).limite_tubos_por_motorista
        finally:
            connection.close()

    def test_cambiar_limites_espera_a_confirmar_la_validacion_en_curso(self):
        for modo in ("CORPORATIVO", "EXTERNO"):
            with self.subTest(modo=modo), override_settings(MODO_APLICACION=modo):
                tomado, iniciado, liberar = threading.Event(), threading.Event(), threading.Event()
                lectores, escritores = [], []
                with ThreadPoolExecutor(max_workers=2) as grupo:
                    lector = grupo.submit(self._leer, self.motoristas[0].pk, tomado, liberar, lectores)
                    try:
                        self.assertTrue(tomado.wait(5))
                        escritor = grupo.submit(self._escribir, modo, iniciado, escritores)
                        self.assertTrue(iniciado.wait(5))
                        fin, bloqueado = time.monotonic() + 5, False
                        while time.monotonic() < fin:
                            with connection.cursor() as cursor:
                                cursor.execute("SELECT pg_blocking_pids(%s)", [escritores[0]])
                                bloqueado = lectores[0] in cursor.fetchone()[0]
                            if bloqueado:
                                break
                            threading.Event().wait(0.02)
                        self.assertTrue(bloqueado, "El escritor debe esperar la transacción que está validando cupos.")
                    finally:
                        liberar.set()
                    self.assertEqual(lector.result(5)["limite_tubos"], 20)
                    self.assertEqual(escritor.result(5), 30)
