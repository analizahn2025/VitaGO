"""Configuración mixta sin compartir claves ni conectar bases durante pruebas."""

from pathlib import Path
import tempfile

from django.test import SimpleTestCase

from scripts.docker.iniciar import orden_compose
from scripts.docker.preparar_en_linea import leer_entorno, preparar, validar_corporativo


class PruebasDockerEnLinea(SimpleTestCase):
    def setUp(self):
        self.temporal = self.enterContext(tempfile.TemporaryDirectory())
        self.raiz = Path(self.temporal)
        self.datos = {"MODO_APLICACION": "CORPORATIVO", "PROVEEDOR_AUTENTICACION": "LOCAL", "ENTORNO": "PRUEBAS",
                      "URL_BASE_DATOS": "postgresql://cuenta:prueba@postgres.example.test:5432/vitago_corporativo",
                      "NOMBRE_BASE_DATOS": "vitago_corporativo", "CLAVE_SECRETA": "a" * 64,
                      "CLAVE_FIRMA_JWT_LOCAL": "b" * 64, "CLAVE_HASH_TOKEN_REFRESCO_LOCAL": "c" * 64}
        self.origen = "\n".join(f"{k}={v}" for k, v in self.datos.items()) + "\n"
        (self.raiz / ".env.render.corporativo").write_text(self.origen)
        (self.raiz / ".env.docker").write_text("CLAVES_NETWORK=CONSERVAR\n")
    def test_reutiliza_corporate_sin_copias_ni_modificar_claves_network(self):
        self.assertEqual(preparar(self.raiz), self.raiz / ".env.render.corporativo")
        self.assertFalse((self.raiz / ".env.docker.corporativo").exists())
        self.assertEqual((self.raiz / ".env.render.corporativo").read_text(), self.origen)
        self.assertEqual((self.raiz / ".env.docker").read_text(), "CLAVES_NETWORK=CONSERVAR\n")

    def test_no_sobrescribe_configuracion_ya_preparada(self):
        preparar(self.raiz)
        (self.raiz / ".env.docker").write_text("PUBLICAR_EN=127.0.0.1\n")
        preparar(self.raiz)
        self.assertEqual((self.raiz / ".env.docker").read_text(), "PUBLICAR_EN=127.0.0.1\n")

    def test_valida_el_archivo_corporate_elegido_sin_usar_otro_por_defecto(self):
        (self.raiz / ".env.docker").write_text("ARCHIVO_ENV_CORPORATIVO=.env.corporate-privado\n")
        with self.assertRaises(ValueError):
            preparar(self.raiz)
        (self.raiz / ".env.corporate-privado").write_text(self.origen)
        self.assertEqual(preparar(self.raiz), self.raiz / ".env.corporate-privado")

    def test_rechaza_base_ajena_o_compartida(self):
        for nombre in ("db_prueba", "vitago", "otra_base"):
            with self.subTest(nombre=nombre), self.assertRaises(ValueError):
                validar_corporativo({**self.datos, "URL_BASE_DATOS": f"postgresql://prueba@ejemplo.test/{nombre}"})

    def test_rechaza_conexion_local_en_modo_linea(self):
        for host in ("localhost", "127.0.0.1", "bd_corporativa", "bd_network", "host.docker.internal"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                validar_corporativo({**self.datos, "URL_BASE_DATOS": f"postgresql://prueba@{host}/vitago_corporativo"})

    def test_no_acepta_claves_repetidas(self):
        with self.assertRaises(ValueError):
            validar_corporativo({**self.datos, "CLAVE_FIRMA_JWT_LOCAL": self.datos["CLAVE_SECRETA"]})

    def test_lectura_no_modifica_entorno_del_proceso(self):
        import os
        anteriores = dict(os.environ)
        self.assertEqual(leer_entorno(self.raiz / ".env.render.corporativo")["CLAVE_SECRETA"], self.datos["CLAVE_SECRETA"])
        self.assertEqual(dict(os.environ), anteriores)

    def test_orden_resuelve_rutas_desde_otra_carpeta_sin_combinar_variantes(self):
        orden = orden_compose(self.raiz)
        self.assertEqual(orden.count("--env-file"), 1)
        self.assertEqual(orden.count("-f"), 1)
        self.assertIn(str(self.raiz / "docker-compose.yml"), orden)
        self.assertIn(str(self.raiz / ".env.docker"), orden)
        self.assertIn(str(self.raiz), orden)

    def test_falta_origen_no_crea_configuraciones_vacias(self):
        (self.raiz / ".env.render.corporativo").unlink()
        with self.assertRaises(ValueError):
            preparar(self.raiz)
        self.assertFalse((self.raiz / ".env.docker.corporativo").exists())
