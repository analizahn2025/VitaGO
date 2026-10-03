import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import SimpleTestCase, override_settings
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIRequestFactory

from apps.autenticacion.autenticadores import (
    AutenticacionCorporativaJWT,
    AutenticacionLocalJWT,
    AutenticacionVitaGo,
)
from apps.autenticacion.models import SesionAutenticacion
from apps.autenticacion.servicios.tokens import crear_par_tokens
from apps.usuarios.models import Usuario


class PruebasAutenticacionCorporativa(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        clave_privada = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        cls.clave_privada = clave_privada.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        cls.clave_publica = clave_privada.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")
        cls.fabrica = APIRequestFactory()

    def _crear_token(self, **cambios):
        claims = {
            "sub": "identidad-corporativa-123",
            "iss": "sistema-corporativo",
            "aud": "vitago-corporativo",
            "exp": datetime.now(tz=UTC) + timedelta(minutes=5),
        }
        claims.update(cambios)
        return jwt.encode(claims, self.clave_privada, algorithm="RS256")

    @override_settings(
        ALGORITMO_JWT_CORPORATIVO="RS256",
        EMISOR_JWT_CORPORATIVO="sistema-corporativo",
        AUDIENCIA_JWT_CORPORATIVO="vitago-corporativo",
        CLAIM_IDENTIDAD_JWT_CORPORATIVO="sub",
        SEGUNDOS_TOLERANCIA_RELOJ_JWT=0,
    )
    def test_valida_firma_claims_y_usuario_local(self):
        usuario = Usuario(
            correo="corporativo@example.com",
            nombres="Usuario",
            apellidos="Corporativo",
            identificador_autenticacion_externa="identidad-corporativa-123",
        )
        solicitud = self.fabrica.get(
            "/protegido/",
            HTTP_AUTHORIZATION=f"Bearer {self._crear_token()}",
        )

        with override_settings(
            CLAVE_PUBLICA_JWT_CORPORATIVO=self.clave_publica
        ), patch(
            "apps.autenticacion.autenticadores.Usuario.objetos.get",
            return_value=usuario,
        ) as buscar_usuario:
            usuario_autenticado, claims = (
                AutenticacionCorporativaJWT().authenticate(solicitud)
            )

        self.assertIs(usuario_autenticado, usuario)
        self.assertEqual(claims["sub"], "identidad-corporativa-123")
        buscar_usuario.assert_called_once_with(
            identificador_autenticacion_externa="identidad-corporativa-123"
        )

    @override_settings(
        ALGORITMO_JWT_CORPORATIVO="RS256",
        EMISOR_JWT_CORPORATIVO="sistema-corporativo",
        AUDIENCIA_JWT_CORPORATIVO="vitago-corporativo",
        CLAIM_IDENTIDAD_JWT_CORPORATIVO="sub",
        SEGUNDOS_TOLERANCIA_RELOJ_JWT=0,
    )
    def test_rechaza_audiencia_incorrecta(self):
        solicitud = self.fabrica.get(
            "/protegido/",
            HTTP_AUTHORIZATION=(
                f"Bearer {self._crear_token(aud='otra-aplicacion')}"
            ),
        )

        with override_settings(
            CLAVE_PUBLICA_JWT_CORPORATIVO=self.clave_publica
        ), self.assertRaises(AuthenticationFailed):
            AutenticacionCorporativaJWT().authenticate(solicitud)


class PruebasAutenticacionLocal(SimpleTestCase):
    def test_token_acceso_requiere_sesion_vigente(self):
        usuario = Usuario(
            correo="externo@example.com",
            nombres="Usuario",
            apellidos="Externo",
        )
        sesion_id = uuid.uuid4()
        familia = uuid.uuid4()
        tokens = crear_par_tokens(usuario, sesion_id, familia)
        sesion = SimpleNamespace(
            id=sesion_id,
            usuario=usuario,
            usuario_id=usuario.id,
            familia=familia,
        )
        solicitud = APIRequestFactory().get(
            "/protegido/",
            HTTP_AUTHORIZATION=f"Bearer {tokens.token_acceso}",
        )

        with patch(
            "apps.autenticacion.autenticadores."
            "SesionAutenticacion.objetos.select_related"
        ) as seleccionar:
            seleccionar.return_value.get.return_value = sesion
            usuario_autenticado, _ = AutenticacionLocalJWT().authenticate(
                solicitud
            )

        self.assertIs(usuario_autenticado, usuario)

    def test_rechaza_token_si_sesion_no_existe(self):
        usuario = Usuario(
            correo="externo@example.com",
            nombres="Usuario",
            apellidos="Externo",
        )
        tokens = crear_par_tokens(usuario, uuid.uuid4(), uuid.uuid4())
        solicitud = APIRequestFactory().get(
            "/protegido/",
            HTTP_AUTHORIZATION=f"Bearer {tokens.token_acceso}",
        )

        with patch(
            "apps.autenticacion.autenticadores."
            "SesionAutenticacion.objetos.select_related"
        ) as seleccionar, self.assertRaises(AuthenticationFailed):
            seleccionar.return_value.get.side_effect = (
                SesionAutenticacion.DoesNotExist
            )
            AutenticacionLocalJWT().authenticate(solicitud)

    @override_settings(PROVEEDOR_AUTENTICACION="LOCAL")
    @patch(
        "apps.autenticacion.autenticadores.AutenticacionLocalJWT.authenticate"
    )
    def test_selector_utiliza_proveedor_local_en_corporativo(
        self,
        autenticar_local,
    ):
        solicitud = APIRequestFactory().get("/protegido/")

        AutenticacionVitaGo().authenticate(solicitud)

        autenticar_local.assert_called_once_with(solicitud)
