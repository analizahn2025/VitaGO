"""CORS para la web administrativa sin modificar autenticación ni clientes nativos."""

from django.test import SimpleTestCase, override_settings


ORIGEN_WEB = "https://frontend-web-eight-self.vercel.app"


@override_settings(CORS_ALLOWED_ORIGINS=[ORIGEN_WEB])
class PruebasCorsAPI(SimpleTestCase):
    def preflight(self, origen=ORIGEN_WEB, metodo="POST"):
        return self.client.options(
            "/api/v1/autenticacion/iniciar-sesion/",
            HTTP_ORIGIN=origen,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD=metodo,
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,content-type",
        )

    def test_preflight_autoriza_web_y_headers_jwt_sin_cookies(self):
        respuesta = self.preflight()

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta["Access-Control-Allow-Origin"], ORIGEN_WEB)
        self.assertIn("POST", respuesta["Access-Control-Allow-Methods"])
        self.assertIn("authorization", respuesta["Access-Control-Allow-Headers"])
        self.assertIn("content-type", respuesta["Access-Control-Allow-Headers"])
        self.assertNotIn("Access-Control-Allow-Credentials", respuesta)
        self.assertIn(
            "origin", {campo.strip().lower() for campo in respuesta["Vary"].split(",")},
        )

    def test_preflight_permite_patch_administrativo(self):
        respuesta = self.preflight(metodo="PATCH")

        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("PATCH", respuesta["Access-Control-Allow-Methods"])
        self.assertEqual(respuesta["Access-Control-Allow-Origin"], ORIGEN_WEB)

    def test_web_autorizada_recibe_cors_en_respuesta_real(self):
        respuesta = self.client.get("/api/v1/salud/", HTTP_ORIGIN=ORIGEN_WEB)

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta["Access-Control-Allow-Origin"], ORIGEN_WEB)
        self.assertIn("Retry-After", respuesta["Access-Control-Expose-Headers"])

    def test_otro_dominio_o_preview_no_recibe_autorizacion(self):
        for origen in (
            "https://otra-web.vercel.app",
            "https://frontend-web-eight-self-git-pruebas.vercel.app",
            ORIGEN_WEB + ".otro.test",
            "http://frontend-web-eight-self.vercel.app",
            "null",
        ):
            with self.subTest(origen=origen):
                respuesta = self.preflight(origen=origen)
                self.assertNotIn("Access-Control-Allow-Origin", respuesta)

    def test_cors_no_sustituye_autenticacion(self):
        respuesta = self.client.get("/api/v1/rutas/mi-ruta/", HTTP_ORIGIN=ORIGEN_WEB)

        self.assertEqual(respuesta.status_code, 401)
        self.assertEqual(respuesta["Access-Control-Allow-Origin"], ORIGEN_WEB)

    def test_cliente_movil_sin_origin_conserva_respuesta(self):
        respuesta = self.client.get("/api/v1/salud/")

        self.assertEqual(respuesta.status_code, 200)
        self.assertNotIn("Access-Control-Allow-Origin", respuesta)

    @override_settings(CORS_ALLOWED_ORIGINS=[])
    def test_sin_lista_explicita_no_autoriza_web(self):
        respuesta = self.preflight()

        self.assertNotIn("Access-Control-Allow-Origin", respuesta)

    def test_fuera_de_la_api_no_expone_cors(self):
        respuesta = self.client.get("/fuera-de-api/", HTTP_ORIGIN=ORIGEN_WEB)

        self.assertEqual(respuesta.status_code, 404)
        self.assertNotIn("Access-Control-Allow-Origin", respuesta)
