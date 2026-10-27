"""Concurrencia real: solo PostgreSQL y bases exclusivas de pruebas."""

import json
import os
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.db import connection, connections
from django.test import TransactionTestCase, override_settings, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.test import APIClient

from apps.autenticacion.models import ControlIntentosInicioSesion, SesionAutenticacion
from apps.usuarios.models import Usuario


@skipUnlessDBFeature("has_select_for_update")
@override_settings(
    PROVEEDOR_AUTENTICACION="LOCAL",
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class PruebasConcurrenciaInicioSesion(TransactionTestCase):
    @classmethod
    def _comprobar_base_temporal(cls):
        base = connection.settings_dict["NAME"]
        if not base.startswith(("test_", "vitago_pruebas_concurrencia_")):
            raise RuntimeError("No ejecutar concurrencia sobre una base de desarrollo o producción.")
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            if cursor.fetchone()[0] != base:
                raise RuntimeError("La conexión no apunta a la base temporal configurada.")

    @classmethod
    def _pre_setup(cls):
        # Proteger también las operaciones de fixtures, antes del setUp normal.
        cls._comprobar_base_temporal()
        super()._pre_setup()

    def _fixture_teardown(self):
        self._comprobar_base_temporal()
        super()._fixture_teardown()

    def setUp(self):
        self.base = connection.settings_dict["NAME"]
        self.correo = "concurrencia@example.test"
        self.contrasena = "Clave-sintetica-para-concurrencia!"
        self.usuario = Usuario.objetos.create(
            correo=self.correo, nombres="Prueba", apellidos="Concurrencia",
            password=make_password(self.contrasena),
        )

    def _login(self, *, correcta=False, ip="192.0.2.10", reenviada=None):
        metadatos = {"REMOTE_ADDR": ip}
        if reenviada is not None:
            metadatos["HTTP_X_FORWARDED_FOR"] = reenviada
        return APIClient().post(
            "/api/v1/autenticacion/iniciar-sesion/",
            {"correo": self.correo, "contrasena": self.contrasena if correcta else "incorrecta"},
            format="json", **metadatos,
        )

    def _paralelas(self, cantidad=24, *, correcta=False, dos_ips=False):
        barrera = Barrier(cantidad, timeout=15)

        def solicitar(indice):
            try:
                propia = connections["default"]
                self.assertEqual(propia.settings_dict["NAME"], self.base)
                with propia.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                    cursor.execute("SET statement_timeout = '20s'")
                    cursor.execute("SELECT current_database(), pg_backend_pid()")
                    base, proceso = cursor.fetchone()
                    self.assertEqual(base, self.base)
                barrera.wait()
                ip = "192.0.2.11" if dos_ips and indice % 2 else "192.0.2.10"
                respuesta = self._login(correcta=correcta, ip=ip, reenviada=f"203.0.113.{indice + 1}")
                espera = int(respuesta.get("Retry-After", 0))
                if respuesta.status_code == 429:
                    self.assertEqual(espera, respuesta.data["segundos_espera"])
                    self.assertGreater(espera, 0)
                return respuesta.status_code, espera, proceso, ip
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=cantidad) as ejecutor:
            resultados = list(ejecutor.map(solicitar, range(cantidad)))
        self.assertEqual(len({fila[2] for fila in resultados}), cantidad)
        return resultados

    def test_contador_nuevo_serializa_24_peticiones_y_no_confia_en_forwarded_for(self):
        resultados = self._paralelas()
        self.assertEqual(Counter(fila[0] for fila in resultados), {401: 10, 429: 14})
        self.assertEqual(ControlIntentosInicioSesion.objects.get().intentos_fallidos, 10)
        self.assertFalse(SesionAutenticacion.objetos.exists())
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.is_active)

    def test_con_nueve_fallos_solo_queda_una_evaluacion_disponible(self):
        for _ in range(9):
            self.assertEqual(self._login().status_code, 401)
        resultados = self._paralelas()
        self.assertEqual(Counter(fila[0] for fila in resultados), {401: 1, 429: 23})
        self.assertEqual(ControlIntentosInicioSesion.objects.get().intentos_fallidos, 10)

    def test_ventana_vencida_no_se_reinicia_varias_veces_en_paralelo(self):
        self.assertEqual(self._login().status_code, 401)
        ControlIntentosInicioSesion.objects.update(
            intentos_fallidos=10, ventana_iniciada_en=timezone.now() - timedelta(minutes=16),
        )
        antes = timezone.now()
        resultados = self._paralelas()
        self.assertEqual(Counter(fila[0] for fila in resultados), {401: 10, 429: 14})
        control = ControlIntentosInicioSesion.objects.get()
        self.assertEqual(control.intentos_fallidos, 10)
        self.assertGreaterEqual(control.ventana_iniciada_en, antes)

    def test_dos_ips_simultaneas_tienen_sus_diez_fallos_independientes(self):
        resultados = self._paralelas(dos_ips=True)
        for ip in ("192.0.2.10", "192.0.2.11"):
            self.assertEqual(Counter(fila[0] for fila in resultados if fila[3] == ip), {401: 10, 429: 2})
        self.assertEqual(list(ControlIntentosInicioSesion.objects.values_list("intentos_fallidos", flat=True)), [10, 10])

    def test_accesos_correctos_concurrentes_no_consumen_fallos(self):
        for _ in range(9):
            self.assertEqual(self._login().status_code, 401)
        resultados = self._paralelas(correcta=True)
        self.assertEqual(Counter(fila[0] for fila in resultados), {200: 24})
        self.assertEqual(ControlIntentosInicioSesion.objects.get().intentos_fallidos, 0)
        self.assertEqual(SesionAutenticacion.objetos.filter(revocado_en__isnull=True).count(), 24)

    def test_atomic_requests_no_revierte_contadores_al_responder_401(self):
        with patch.dict(connection.settings_dict, {"ATOMIC_REQUESTS": True}):
            for _ in range(10):
                self.assertEqual(self._login().status_code, 401)
            self.assertEqual(self._login(correcta=True).status_code, 429)
        self.assertEqual(ControlIntentosInicioSesion.objects.get().intentos_fallidos, 10)

    def test_dos_procesos_de_aplicacion_comparten_el_contador(self):
        # Los hijos arrancan Django por separado, sin compartir cachés ni locks
        # de Python. Validan el destino antes de cualquier acceso a la base.
        codigo = r'''
import json, os, sys
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings.local'
from django.conf import settings
base = sys.argv[1]
assert base.startswith(('test_', 'vitago_pruebas_concurrencia_'))
settings.DATABASES['default']['NAME'] = base
settings.DATABASES['default']['CONN_MAX_AGE'] = 0
settings.PROVEEDOR_AUTENTICACION = 'LOCAL'
settings.PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
settings.ALLOWED_HOSTS = ['testserver']
settings.DEBUG = False
import django
django.setup()
from django.db import connection, connections
from rest_framework.test import APIClient
try:
    with connection.cursor() as cursor:
        cursor.execute('SELECT current_database()')
        assert cursor.fetchone()[0] == base
    estados = []
    for _ in range(8):
        respuesta = APIClient().post('/api/v1/autenticacion/iniciar-sesion/',
            {'correo': 'concurrencia@example.test', 'contrasena': 'incorrecta'},
            format='json', REMOTE_ADDR='192.0.2.10')
        estados.append(respuesta.status_code)
    print(json.dumps({'proceso': os.getpid(), 'estados': estados}))
finally:
    connections.close_all()
'''
        procesos = []
        try:
            for _ in range(2):
                procesos.append(subprocess.Popen(
                    [sys.executable, "-c", codigo, self.base],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                ))
            resultados = []
            for proceso in procesos:
                salida, errores = proceso.communicate(timeout=30)
                self.assertEqual(proceso.returncode, 0, errores)
                resultados.append(json.loads(salida))
        finally:
            for proceso in procesos:
                if proceso.poll() is None:
                    proceso.kill()
                    proceso.communicate(timeout=5)
        self.assertEqual(len({fila["proceso"] for fila in resultados}), 2)
        self.assertEqual(Counter(estado for fila in resultados for estado in fila["estados"]), {401: 10, 429: 6})
        self.assertEqual(ControlIntentosInicioSesion.objects.get().intentos_fallidos, 10)
