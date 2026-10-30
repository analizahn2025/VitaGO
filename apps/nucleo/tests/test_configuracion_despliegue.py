"""Verifica el arranque sin leer secretos locales ni conectar bases reales."""

import json
import os
from pathlib import Path
import subprocess
import sys

from django.test import SimpleTestCase


COMPROBAR_CONFIGURACION = """
import json
import sys
from unittest.mock import patch
from django.core.exceptions import ImproperlyConfigured

with patch('environ.Env.read_env'):
    try:
        from config.settings import production as configuracion
        resultado = {
            'depuracion': configuracion.DEBUG,
            'servidores': configuracion.ALLOWED_HOSTS,
            'origenes_web': configuracion.CORS_ALLOWED_ORIGINS,
            'proxy_https': getattr(configuracion, 'SECURE_PROXY_SSL_HEADER', None),
            'redireccion_ssl': configuracion.SECURE_SSL_REDIRECT,
            'recuperacion_cierre': configuracion.HABILITAR_RECUPERACION_CIERRE,
            'cookies_seguras': (
                configuracion.SESSION_COOKIE_SECURE
                and configuracion.CSRF_COOKIE_SECURE
            ),
        }
        if sys.argv[1] == 'wsgi':
            with patch(
                'django.db.backends.base.base.BaseDatabaseWrapper.ensure_connection',
                side_effect=AssertionError('No conectar bases en esta prueba'),
            ):
                from config.wsgi import application
                from django.test import Client
                cliente = Client()
                host = configuracion.ALLOWED_HOSTS[-1]
                salud = cliente.get(
                    '/api/v1/salud/', HTTP_HOST=host,
                    HTTP_X_FORWARDED_PROTO='https',
                )
                resultado['salud'] = salud.status_code
                resultado['cuerpo_salud'] = salud.json()
                http = cliente.get('/api/v1/salud/', HTTP_HOST=host)
                resultado['http'] = http.status_code
                resultado['redireccion'] = http.get('Location')
    except ImproperlyConfigured as error:
        resultado = {'error': str(error)}
print(json.dumps(resultado))
"""


class PruebasConfiguracionDespliegue(SimpleTestCase):
    def comprobar(self, *, wsgi=False, **cambios):
        # No heredar URL_BASE_DATOS, secretos ni .env del proceso de pruebas.
        entorno = {
            clave: valor
            for clave, valor in os.environ.items()
            if clave.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}
        }
        entorno.update({
            "DJANGO_SETTINGS_MODULE": "config.settings.production",
            "ENTORNO": "PRUEBAS",
            "MODO_APLICACION": "CORPORATIVO",
            "PROVEEDOR_AUTENTICACION": "LOCAL",
            "CLAVE_SECRETA": "s" * 64,
            "CLAVE_FIRMA_JWT_LOCAL": "f" * 64,
            "CLAVE_HASH_TOKEN_REFRESCO_LOCAL": "h" * 64,
            "URL_BASE_DATOS": "postgresql://prueba:prueba@127.0.0.1:65432/prueba",
            "SERVIDORES_PERMITIDOS": "api.example.test",
        })
        if wsgi:
            # Este smoke verifica HTTPS sin una base real; recuperación se prueba aparte.
            entorno["HABILITAR_RECUPERACION_CIERRE"] = "false"
        for clave, valor in cambios.items():
            if valor is None:
                entorno.pop(clave, None)
            else:
                entorno[clave] = valor
        proceso = subprocess.run(
            [sys.executable, "-X", "utf8", "-c", COMPROBAR_CONFIGURACION,
             "wsgi" if wsgi else "configuracion"],
            cwd=Path(__file__).resolve().parents[3],
            env=entorno, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(proceso.returncode, 0, proceso.stderr)
        return json.loads(proceso.stdout)

    def test_corporate_local_en_pruebas_conserva_seguridad(self):
        resultado = self.comprobar(DEPURACION="true")

        self.assertNotIn("error", resultado)
        self.assertFalse(resultado["depuracion"])
        self.assertTrue(resultado["redireccion_ssl"])
        self.assertTrue(resultado["cookies_seguras"])
        self.assertTrue(resultado["recuperacion_cierre"])

    def test_corporate_local_requiere_optar_expresamente_por_pruebas(self):
        for entorno in (None, "LOCAL", "PRODUCCION", "OTRO"):
            with self.subTest(entorno=entorno):
                resultado = self.comprobar(ENTORNO=entorno)
                self.assertIn("ENTORNO=PRUEBAS", resultado["error"])

    def test_network_local_sigue_permitido_en_produccion(self):
        resultado = self.comprobar(MODO_APLICACION="EXTERNO", ENTORNO="PRODUCCION")

        self.assertNotIn("error", resultado)

    def test_jwt_corporativo_sigue_exigiendo_su_configuracion(self):
        resultado = self.comprobar(PROVEEDOR_AUTENTICACION="JWT_CORPORATIVO")

        self.assertIn("CLAVE_PUBLICA_JWT_CORPORATIVO", resultado["error"])

    def test_no_permite_omitir_base_clave_o_servidores(self):
        for clave in ("URL_BASE_DATOS", "CLAVE_SECRETA", "SERVIDORES_PERMITIDOS"):
            with self.subTest(clave=clave):
                resultado = self.comprobar(**{clave: ""})
                self.assertIn(clave, resultado["error"])

    def test_login_local_conserva_validaciones_de_secretos(self):
        casos = (
            ({"ALGORITMO_JWT_LOCAL": "RS256"}, "ALGORITMO_JWT_LOCAL"),
            ({"CLAVE_FIRMA_JWT_LOCAL": "corta"}, "CLAVE_FIRMA_JWT_LOCAL"),
            ({"CLAVE_FIRMA_JWT_LOCAL": "s" * 64}, "CLAVE_FIRMA_JWT_LOCAL"),
            ({"CLAVE_HASH_TOKEN_REFRESCO_LOCAL": "corta"}, "CLAVE_HASH_TOKEN_REFRESCO_LOCAL"),
            ({"CLAVE_HASH_TOKEN_REFRESCO_LOCAL": "f" * 64}, "secreto independiente"),
            ({"CLAVE_HASH_TOKEN_REFRESCO_LOCAL": "s" * 64}, "secreto independiente"),
        )
        for cambios, mensaje in casos:
            with self.subTest(campos=list(cambios)):
                self.assertIn(mensaje, self.comprobar(**cambios)["error"])

    def test_tokens_siguen_exigiendo_duracion_positiva(self):
        for clave in ("MINUTOS_TOKEN_ACCESO", "DIAS_TOKEN_REFRESCO"):
            with self.subTest(clave=clave):
                self.assertIn(clave, self.comprobar(**{clave: "0"})["error"])

    def test_render_autoriza_solo_su_dominio_y_arranca_wsgi_sin_bucle_https(self):
        resultado = self.comprobar(
            wsgi=True, RENDER="true", SERVIDORES_PERMITIDOS="",
            RENDER_EXTERNAL_HOSTNAME="vitago-pruebas.onrender.com",
            ORIGENES_WEB_PERMITIDOS="https://frontend-web-eight-self.vercel.app",
        )

        self.assertEqual(resultado["servidores"], ["vitago-pruebas.onrender.com"])
        self.assertEqual(
            resultado["origenes_web"], ["https://frontend-web-eight-self.vercel.app"],
        )
        self.assertEqual(resultado["proxy_https"], ["HTTP_X_FORWARDED_PROTO", "https"])
        self.assertEqual(resultado["salud"], 200)
        self.assertEqual(resultado["cuerpo_salud"]["estado"], "correcto")
        self.assertEqual(resultado["http"], 301)
        self.assertEqual(
            resultado["redireccion"],
            "https://vitago-pruebas.onrender.com/api/v1/salud/",
        )

    def test_fuera_de_render_no_autoriza_dominio_ni_confia_en_proxy(self):
        resultado = self.comprobar(
            RENDER="false", RENDER_EXTERNAL_HOSTNAME="ignorado.onrender.com",
        )

        self.assertEqual(resultado["servidores"], ["api.example.test"])
        self.assertIsNone(resultado["proxy_https"])

    def test_render_no_duplica_servidores_ni_reemplaza_los_explicitos(self):
        resultado = self.comprobar(
            RENDER="true", RENDER_EXTERNAL_HOSTNAME="api.example.test",
            SERVIDORES_PERMITIDOS="api.example.test,otro.example.test",
        )

        self.assertEqual(resultado["servidores"], ["api.example.test", "otro.example.test"])

    def test_render_sin_dominio_tampoco_permite_omitir_servidores(self):
        resultado = self.comprobar(
            RENDER="true", RENDER_EXTERNAL_HOSTNAME="", SERVIDORES_PERMITIDOS="",
        )

        self.assertIn("SERVIDORES_PERMITIDOS", resultado["error"])
