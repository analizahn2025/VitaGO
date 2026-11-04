"""Arranque, salud y aislamiento de Docker sin usar bases operativas."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import MagicMock, Mock, patch

from django.db import DatabaseError
from django.test import SimpleTestCase
from django.urls import reverse

from scripts.docker import arranque, base_datos, comprobar_salud
from scripts.docker.crear_entorno_local import crear_entorno


class PruebasDisponibilidad(SimpleTestCase):
    def test_disponibilidad_real_devuelve_200_sin_revelar_configuracion(self):
        with patch("apps.nucleo.views.connection") as base:
            cursor = base.cursor
            cursor.return_value.__enter__.return_value.fetchone.return_value = (1,)
            respuesta = self.client.get(reverse("nucleo:disponibilidad"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(set(respuesta.json()), {"estado", "servicio"})
        self.assertEqual(respuesta.json()["estado"], "correcto")
        self.assertEqual(respuesta["Cache-Control"], "no-store")
        cursor.return_value.__enter__.return_value.execute.assert_called_once_with("SELECT 1")

    def test_base_caida_devuelve_503_sin_credenciales(self):
        with patch("apps.nucleo.views.connection") as base:
            base.cursor.side_effect = DatabaseError("postgresql://usuario:secreto@servidor/base")
            respuesta = self.client.get(reverse("nucleo:disponibilidad"))
        self.assertEqual(respuesta.status_code, 503)
        self.assertEqual(respuesta.json()["estado"], "no_disponible")
        self.assertNotIn("secreto", respuesta.content.decode())


class PruebasArranqueDocker(SimpleTestCase):
    def test_prepara_solamente_ordenes_de_servidor(self):
        for orden in (["gunicorn", "config.wsgi:application"], ["python", "-m", "gunicorn"],
                      ["python", "manage.py", "runserver", "0.0.0.0:8000"]):
            self.assertTrue(arranque.es_servidor(orden))
        for orden in ([], ["python", "manage.py", "test"], ["python", "manage.py", "check"],
                      ["python", "manage.py", "migrate"], ["sh"]):
            self.assertFalse(arranque.es_servidor(orden))

    def test_orden_administrativa_no_prepara_ni_espera(self):
        with patch.object(arranque, "esperar_base_datos") as esperar, patch.object(arranque.subprocess, "run") as ejecutar:
            self.assertEqual(arranque.main(["python", "manage.py", "test"]), 0)
            esperar.assert_not_called()
            ejecutar.assert_not_called()

    def test_entrada_de_servidor_rechaza_pruebas_con_configuracion_operativa(self):
        with patch.dict(os.environ, {"DJANGO_SETTINGS_MODULE": "config.settings.contenedor"}), \
                patch.object(arranque, "esperar_base_datos") as esperar:
            self.assertEqual(arranque.main(["python", "manage.py", "test"]), 1)
            esperar.assert_not_called()

    def test_espera_reintenta_y_se_detiene_al_aceptar_select(self):
        with patch.object(arranque.subprocess, "run", side_effect=[Mock(returncode=1), Mock(returncode=0)]) as ejecutar, \
                patch.object(arranque.time, "monotonic", side_effect=[0, 0, 1, 2]), \
                patch.object(arranque.time, "sleep"):
            arranque.esperar_base_datos()
        self.assertEqual(ejecutar.call_count, 2)
        self.assertTrue(ejecutar.call_args.kwargs["capture_output"])

    def test_espera_tiene_limite_aunque_el_driver_se_bloquee(self):
        with patch.object(arranque.subprocess, "run", side_effect=subprocess.TimeoutExpired("python", 3)) as ejecutar, \
                patch.object(arranque.time, "monotonic", side_effect=[0, 0, 2, 3]), \
                patch.object(arranque.time, "sleep") as dormir:
            with self.assertRaises(TimeoutError):
                arranque.esperar_base_datos(segundos=3)
        self.assertEqual(ejecutar.call_args.kwargs["timeout"], 3)
        dormir.assert_called_once_with(1)

    def test_tiempos_invalidos_no_intentan_conectar(self):
        for segundos, intervalo in ((0, 1), (1, 0), (-1, 1), (float("inf"), 1), (1, float("nan"))):
            with self.assertRaises(ValueError):
                arranque.esperar_base_datos(segundos, intervalo)

    def test_fallo_de_migracion_impide_iniciar_gunicorn(self):
        with patch.object(arranque, "esperar_base_datos"), \
                patch.object(arranque.subprocess, "run", return_value=Mock(returncode=3)):
            self.assertEqual(arranque.main(["python", "-m", "gunicorn"]), 3)


class PruebasPreparacionDocker(SimpleTestCase):
    def setUp(self):
        self.base = MagicMock()
        self.base.cursor.return_value.__enter__.return_value.fetchone.return_value = (True,)

    def test_migracion_antes_de_estaticos_y_desbloqueo(self):
        ejecutar = Mock()
        with patch.dict(os.environ, {"APLICAR_MIGRACIONES": "true", "PREPARAR_ESTATICOS": "true"}):
            base_datos.preparar(self.base, ejecutar)
        self.assertEqual([c.args[0] for c in ejecutar.call_args_list], ["migrate", "collectstatic"])
        sql = self.base.cursor.return_value.__enter__.return_value.execute.call_args_list
        self.assertIn("pg_try_advisory_lock", sql[0].args[0])
        self.assertIn("pg_advisory_unlock", sql[-1].args[0])

    def test_error_de_migracion_libera_bloqueo_y_no_prepara_estaticos(self):
        ejecutar = Mock(side_effect=RuntimeError("Fallo sintético"))
        with self.assertRaises(RuntimeError):
            base_datos.preparar(self.base, ejecutar)
        self.assertEqual(ejecutar.call_count, 1)
        self.assertIn("pg_advisory_unlock", self.base.cursor.return_value.__enter__.return_value.execute.call_args.args[0])

    def test_banderas_false_omiten_preparacion_explicita(self):
        ejecutar = Mock()
        with patch.dict(os.environ, {"APLICAR_MIGRACIONES": "false", "PREPARAR_ESTATICOS": "false"}):
            base_datos.preparar(self.base, ejecutar)
        self.base.cursor.assert_not_called()
        ejecutar.assert_not_called()

    def test_bloqueo_ocupado_agota_plazo_sin_migrar(self):
        self.base.cursor.return_value.__enter__.return_value.fetchone.return_value = (False,)
        ejecutar = Mock()
        with patch.dict(os.environ, {"SEGUNDOS_ESPERA_MIGRACIONES": "2"}), \
                patch.object(base_datos.time, "monotonic", side_effect=[0, 0, 3, 3]), \
                patch.object(base_datos.time, "sleep"):
            with self.assertRaises(TimeoutError):
                base_datos.preparar(self.base, ejecutar)
        ejecutar.assert_not_called()


class PruebasSecretosDocker(SimpleTestCase):
    def test_secretos_independientes_y_sin_sobrescribir_env_existente(self):
        with tempfile.TemporaryDirectory() as directorio:
            raiz = Path(directorio)
            claves = ["CLAVE_DB_NETWORK", "CLAVE_SECRETA_NETWORK", "CLAVE_JWT_NETWORK", "CLAVE_REFRESCO_NETWORK"]
            (raiz / ".env.docker.example").write_text("\n".join(f"{k}=GENERAR" for k in claves))
            (raiz / ".env").write_text("no modificar")
            destino = crear_entorno(raiz)
            valores = [linea.split("=", 1)[1] for linea in destino.read_text().splitlines()]
            self.assertEqual(len(set(valores)), 4)
            self.assertTrue(all(len(v) >= 64 for v in valores))
            with self.assertRaises(FileExistsError):
                crear_entorno(raiz)
            self.assertEqual((raiz / ".env").read_text(), "no modificar")


class PruebasHealthcheckDocker(SimpleTestCase):
    def test_exige_http_correcto_y_estado_correcto(self):
        with patch.object(comprobar_salud, "urlopen") as abrir:
            respuesta = abrir.return_value.__enter__.return_value
            respuesta.status = 200
            respuesta.read.return_value = json.dumps({"estado": "correcto"}).encode()
            self.assertEqual(comprobar_salud.main(), 0)
            respuesta.read.return_value = b'{"estado":"no_disponible"}'
            self.assertEqual(comprobar_salud.main(), 1)

    def test_servidor_apagado_es_no_saludable(self):
        with patch.object(comprobar_salud, "urlopen", side_effect=TimeoutError()):
            self.assertEqual(comprobar_salud.main(), 1)


class PruebasConfiguracionContenedor(SimpleTestCase):
    def _comprobar(self, modulo, **cambios):
        entorno = {k: v for k, v in os.environ.items() if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}}
        entorno.update({"CLAVE_SECRETA": "s" * 64, "CLAVE_FIRMA_JWT_LOCAL": "f" * 64,
                        "CLAVE_HASH_TOKEN_REFRESCO_LOCAL": "h" * 64, "ENTORNO": "PRUEBAS",
                        "MODO_APLICACION": "CORPORATIVO", "PROVEEDOR_AUTENTICACION": "LOCAL",
                        "URL_BASE_DATOS": "postgresql://prueba:prueba@ejemplo.test:5432/prueba",
                        "SERVIDORES_PERMITIDOS": "api.example.test"})
        entorno.update(cambios)
        codigo = '''
import importlib,json,sys
from unittest.mock import patch
from django.core.exceptions import ImproperlyConfigured
with patch("environ.Env.read_env"):
    try:
        c=importlib.import_module(sys.argv[1])
        print(json.dumps({"servidores":c.ALLOWED_HOSTS,"proxy":getattr(c,"SECURE_PROXY_SSL_HEADER",None),
            "base":c.DATABASES["default"]["NAME"],"prueba":c.DATABASES["default"].get("TEST",{}),
            "estaticos":str(getattr(c,"STATIC_ROOT",None))}))
    except ImproperlyConfigured:
        print(json.dumps({"rechazada":True}))
'''
        resultado = subprocess.run([sys.executable, "-c", codigo, modulo], cwd=Path(__file__).resolve().parents[3],
                                   env=entorno, capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        return json.loads(resultado.stdout)

    def test_configuracion_tiene_paths_internos_y_proxy_solo_explicito(self):
        datos = self._comprobar("config.settings.contenedor")
        self.assertIn("api.example.test", datos["servidores"])
        self.assertIn("127.0.0.1", datos["servidores"])
        self.assertIsNone(datos["proxy"])
        self.assertTrue(datos["estaticos"].endswith("staticfiles"))
        datos = self._comprobar("config.settings.contenedor", CONFIAR_PROXY_HTTPS="true")
        self.assertEqual(datos["proxy"], ["HTTP_X_FORWARDED_PROTO", "https"])

    def test_pruebas_postgresql_rechazan_base_operativa(self):
        datos = self._comprobar("config.settings.pruebas_postgresql",
                               URL_BASE_DATOS_PRUEBAS="postgresql://prueba:prueba@servidor-real:5432/vitago_corporativo")
        self.assertTrue(datos["rechazada"])

    def test_pruebas_postgresql_usan_destino_exclusivo(self):
        datos = self._comprobar("config.settings.pruebas_postgresql",
                               URL_BASE_DATOS_PRUEBAS="postgresql://prueba:prueba@bd_pruebas:5432/vitago_pruebas_docker")
        self.assertEqual(datos["base"], "vitago_pruebas_docker")
        self.assertEqual(datos["prueba"], {"NAME": "test_vitago_docker"})
