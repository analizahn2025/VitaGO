import uuid

from django.test import SimpleTestCase
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.autenticacion.servicios.tokens import (
    calcular_hash_token_refresco,
    crear_par_tokens,
)
from apps.usuarios.models import Usuario


class PruebasTokensExternos(SimpleTestCase):
    def setUp(self):
        self.usuario = Usuario(
            correo="externo@example.com",
            nombres="Usuario",
            apellidos="Externo",
        )

    def test_par_tokens_incluye_sesion_familia_y_usuario(self):
        sesion_id = uuid.uuid4()
        familia = uuid.uuid4()

        resultado = crear_par_tokens(self.usuario, sesion_id, familia)
        token_refresco = RefreshToken(resultado.token_refresco)
        token_acceso = AccessToken(resultado.token_acceso)

        for token in (token_refresco, token_acceso):
            self.assertEqual(token["sesion_id"], str(sesion_id))
            self.assertEqual(token["familia"], str(familia))
            self.assertEqual(token["usuario_id"], str(self.usuario.id))

    def test_hash_token_es_determinista_y_no_expone_token(self):
        token = "token-refresco-de-prueba"

        primer_hash = calcular_hash_token_refresco(token)
        segundo_hash = calcular_hash_token_refresco(token)

        self.assertEqual(primer_hash, segundo_hash)
        self.assertEqual(len(primer_hash), 64)
        self.assertNotEqual(primer_hash, token)
        self.assertNotIn(token, primer_hash)
