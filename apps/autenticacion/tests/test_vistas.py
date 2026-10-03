from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from apps.autenticacion.excepciones import (
    CredencialesInvalidas,
    TokenRefrescoInvalido,
)
from apps.autenticacion.serializadores import (
    SerializadorInicioSesion,
    SerializadorRenovacionToken,
)


class PruebasDisponibilidadEndpoints(SimpleTestCase):
    @override_settings(
        MODO_APLICACION="CORPORATIVO",
        PROVEEDOR_AUTENTICACION="JWT_CORPORATIVO",
    )
    def test_inicio_sesion_local_no_disponible_con_jwt_corporativo(self):
        respuesta = self.client.post(
            reverse("autenticacion:iniciar-sesion"),
            {
                "correo": "usuario@example.com",
                "contrasena": "contrasena-de-prueba",
            },
            content_type="application/json",
        )

        self.assertEqual(respuesta.status_code, 404)
        self.assertEqual(
            respuesta.json()["detail"],
            (
                "Este endpoint no está disponible con el proveedor "
                "de autenticación actual."
            ),
        )

    @override_settings(
        MODO_APLICACION="CORPORATIVO",
        PROVEEDOR_AUTENTICACION="LOCAL",
    )
    def test_inicio_sesion_local_disponible_en_corporativo_local(self):
        respuesta = self.client.post(
            reverse("autenticacion:iniciar-sesion"),
            {},
            content_type="application/json",
        )

        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("correo", respuesta.json())
        self.assertIn("contrasena", respuesta.json())

    @override_settings(
        MODO_APLICACION="EXTERNO",
        PROVEEDOR_AUTENTICACION="LOCAL",
    )
    def test_inicio_sesion_valida_contrato_entrada(self):
        respuesta = self.client.post(
            reverse("autenticacion:iniciar-sesion"),
            {},
            content_type="application/json",
        )

        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("correo", respuesta.json())
        self.assertIn("contrasena", respuesta.json())

    def test_inicio_sesion_solo_declara_correo_y_contrasena(self):
        campos = set(SerializadorInicioSesion().fields)

        self.assertEqual(campos, {"correo", "contrasena"})

    def test_renovacion_solo_declara_token_refresco(self):
        campos = set(SerializadorRenovacionToken().fields)

        self.assertEqual(campos, {"token_refresco"})

    @override_settings(PROVEEDOR_AUTENTICACION="LOCAL")
    @patch(
        "apps.autenticacion.vistas.autenticar_usuario_local",
        side_effect=CredencialesInvalidas(),
    )
    def test_credenciales_invalidas_responden_401(self, _autenticar):
        respuesta = self.client.post(
            reverse("autenticacion:iniciar-sesion"),
            {
                "correo": "usuario@example.com",
                "contrasena": "contrasena-incorrecta",
            },
            content_type="application/json",
        )

        self.assertEqual(respuesta.status_code, 401)
        self.assertEqual(respuesta.json()["detail"], "Credenciales inválidas.")
        self.assertEqual(respuesta["WWW-Authenticate"], "Bearer")

    @override_settings(PROVEEDOR_AUTENTICACION="LOCAL")
    @patch(
        "apps.autenticacion.vistas.renovar_sesion",
        side_effect=TokenRefrescoInvalido(),
    )
    def test_token_refresco_invalido_responde_401(self, _renovar):
        respuesta = self.client.post(
            reverse("autenticacion:renovar"),
            {"token_refresco": "token-invalido"},
            content_type="application/json",
        )

        self.assertEqual(respuesta.status_code, 401)
        self.assertEqual(
            respuesta.json()["detail"],
            "El token de refresco no es válido.",
        )
        self.assertEqual(respuesta["WWW-Authenticate"], "Bearer")
