"""Regresión de errores públicos y censura, solo con secretos sintéticos."""

import sys

from django.core.exceptions import BadRequest
from django.http import JsonResponse
from django.test import Client, RequestFactory, SimpleTestCase, override_settings
from django.urls import path
from rest_framework.exceptions import AuthenticationFailed, Throttled, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from apps.nucleo.seguridad import FiltroInformeErroresSeguro, InformeErroresSeguro


def _fallo_interno(request):
    raise RuntimeError("detalle interno sintético que no debe ser público")


def _solicitud_invalida(request):
    raise BadRequest("detalle privado sintético")


def _error_json_interno(request):
    return JsonResponse({"detail": "detalle privado sintético"}, status=500)


class _Validacion(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)

    def get(self, request):
        raise ValidationError({"correo": ["Correo inválido."]})


class _NoAutenticado(_Validacion):
    def get_authenticate_header(self, request):
        return "Bearer"

    def get(self, request):
        raise AuthenticationFailed("Credenciales no válidas.")


class _Limite(_Validacion):
    def get(self, request):
        raise Throttled(wait=30)


urlpatterns = [
    path("api/error/", _fallo_interno),
    path("api/incorrecta/", _solicitud_invalida),
    path("api/error-json/", _error_json_interno),
    path("api/validacion/", _Validacion.as_view()),
    path("api/autenticacion/", _NoAutenticado.as_view()),
    path("api/limite/", _Limite.as_view()),
    path("privado/error/", _fallo_interno),
]


@override_settings(DEBUG=True)
class PruebasFiltroInformeErrores(SimpleTestCase):
    def setUp(self):
        self.filtro = FiltroInformeErroresSeguro()
        self.peticion = RequestFactory().post(
            "/api/autenticacion/",
            {"correo": "sintetico@example.test", "contrasena": "solo-sintetica"},
            HTTP_AUTHORIZATION="Bearer token-sintetico",
        )

    def test_censura_nombres_espanoles_e_ingleses_incluso_con_debug(self):
        self.assertTrue(self.filtro.is_active(self.peticion))
        for nombre in (
            "CLAVE_FIRMA_JWT_LOCAL", "CLAVE_HASH_TOKEN_REFRESCO_LOCAL",
            "CLAVE_FIRMA_JWT_LOCAL_BASE", "contrasena", "contraseña",
            "CREDENCIALES", "SECRETO_CORREO", "URL_BASE_DATOS",
            "SECRET_KEY", "PASSWORD", "HTTP_AUTHORIZATION",
        ):
            with self.subTest(nombre=nombre):
                self.assertEqual(
                    self.filtro.cleanse_setting(nombre, "valor-sintetico"),
                    self.filtro.cleansed_substitute,
                )

    def test_censura_diccionarios_anidados_sin_ocultar_configuracion_inocua(self):
        valor = self.filtro.cleanse_setting(
            "CONFIGURACION", {"anidado": [{"clave": "sintetica", "limite": 5}]}
        )
        self.assertEqual(valor["anidado"][0]["limite"], 5)
        self.assertEqual(
            valor["anidado"][0]["clave"], self.filtro.cleansed_substitute
        )

    def test_censura_post_y_meta_sin_modificar_la_solicitud(self):
        ocultos = self.filtro.get_post_parameters(self.peticion)
        self.assertEqual(set(ocultos.values()), {self.filtro.cleansed_substitute})
        self.assertEqual(self.peticion.POST["contrasena"], "solo-sintetica")
        self.assertEqual(
            self.filtro.get_safe_request_meta(self.peticion)["HTTP_AUTHORIZATION"],
            self.filtro.cleansed_substitute,
        )

    def test_censura_variables_aunque_secreto_use_nombre_generico(self):
        valor = {"contrasena": "solo-sintetica"}
        variables = dict(
            self.filtro.get_traceback_frame_variables(self.peticion, sys._getframe())
        )
        self.assertEqual(variables["valor"], self.filtro.cleansed_substitute)
        self.assertEqual(valor["contrasena"], "solo-sintetica")

    def test_informe_http_no_contiene_excepcion_ni_configuracion(self):
        informe = InformeErroresSeguro(
            self.peticion, RuntimeError, RuntimeError("detalle-sintetico-privado"), None
        )
        for contenido in (informe.get_traceback_html(), informe.get_traceback_text()):
            self.assertNotIn("detalle-sintetico-privado", contenido)
            self.assertNotIn("solo-sintetica", contenido)
            self.assertNotIn("CLAVE_FIRMA", contenido)


@override_settings(
    ROOT_URLCONF=__name__,
    ALLOWED_HOSTS=["testserver"],
    DEBUG=True,
    CLAVE_FIRMA_JWT_LOCAL="secreto-jwt-exclusivamente-sintetico",
)
class PruebasErroresSegurosHTTP(SimpleTestCase):
    def setUp(self):
        self.cliente = Client(raise_request_exception=False)

    def test_host_no_autorizado_devuelve_400_json_sin_secretos(self):
        respuesta = self.cliente.get("/api/error/", HTTP_HOST="no-autorizado.test")
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(respuesta.json(), {"detail": "La solicitud no es válida."})
        self.assertNotContains(
            respuesta, "secreto-jwt-exclusivamente-sintetico", status_code=400
        )
        self.assertNotContains(respuesta, "Traceback", status_code=400)

    def test_host_no_autorizado_fuera_api_tampoco_expone_informe(self):
        respuesta = self.cliente.get("/", HTTP_HOST="no-autorizado.test")
        self.assertEqual(respuesta.status_code, 400)
        self.assertNotContains(
            respuesta, "secreto-jwt-exclusivamente-sintetico", status_code=400
        )
        self.assertNotContains(respuesta, "DisallowedHost", status_code=400)

    def test_error_inesperado_es_json_y_conserva_log_y_tiempo(self):
        with self.assertLogs("django.request", level="ERROR") as registros:
            respuesta = self.cliente.get("/api/error/")
        self.assertEqual(respuesta.status_code, 500)
        self.assertEqual(set(respuesta.json()), {"detail"})
        self.assertNotContains(respuesta, "detalle interno", status_code=500)
        self.assertEqual(respuesta["Cache-Control"], "no-store")
        self.assertIn("Server-Timing", respuesta)
        self.assertIsNotNone(registros.records[0].exc_info)

    @override_settings(DEBUG=False)
    def test_error_inesperado_con_debug_desactivado_tambien_es_json(self):
        respuesta = self.cliente.get("/api/error/")
        self.assertEqual(respuesta.status_code, 500)
        self.assertEqual(set(respuesta.json()), {"detail"})

    def test_error_500_json_no_expone_mensaje_interno(self):
        respuesta = self.cliente.get("/api/error-json/")
        self.assertEqual(respuesta.status_code, 500)
        self.assertNotIn("detalle privado", respuesta.content.decode())

    def test_error_400_django_conserva_estado_y_no_expone_detalles(self):
        respuesta = self.cliente.get("/api/incorrecta/")
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(respuesta.json(), {"detail": "La solicitud no es válida."})

    def test_error_404_api_no_expone_configuracion_urls(self):
        respuesta = self.cliente.get("/api/no-existe/")
        self.assertEqual(respuesta.status_code, 404)
        self.assertEqual(
            respuesta.json(), {"detail": "No se encontró el recurso solicitado."}
        )

    def test_error_validacion_conserva_campos(self):
        respuesta = self.cliente.get("/api/validacion/")
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(respuesta.json(), {"correo": ["Correo inválido."]})

    def test_error_401_conserva_estado_cuerpo_y_bearer(self):
        respuesta = self.cliente.get("/api/autenticacion/")
        self.assertEqual(respuesta.status_code, 401)
        self.assertEqual(respuesta["WWW-Authenticate"], "Bearer")
        self.assertEqual(respuesta.json(), {"detail": "Credenciales no válidas."})

    def test_error_429_conserva_retry_after(self):
        respuesta = self.cliente.get("/api/limite/")
        self.assertEqual(respuesta.status_code, 429)
        self.assertEqual(respuesta["Retry-After"], "30")

    def test_error_fuera_api_no_publica_informe_tecnico_con_debug(self):
        respuesta = self.cliente.get("/privado/error/")
        self.assertEqual(respuesta.status_code, 500)
        self.assertNotContains(respuesta, "detalle interno", status_code=500)
        self.assertNotContains(respuesta, "Traceback", status_code=500)
