from unittest.mock import patch

from django.test import SimpleTestCase

from apps.autenticacion.servicios.credenciales import (
    autenticar_usuario_local,
)
from apps.usuarios.models import Usuario


class PruebasCredencialesLocales(SimpleTestCase):
    def test_busca_correo_normalizado_mediante_indice_exacto(self):
        usuario = Usuario(
            correo="usuario@example.com",
            nombres="Usuario",
            apellidos="Externo",
        )
        usuario.set_password("contrasena-de-prueba")

        with patch.object(
            Usuario.objetos,
            "get",
            return_value=usuario,
        ) as buscar_usuario:
            resultado = autenticar_usuario_local(
                "USUARIO@Example.COM",
                "contrasena-de-prueba",
            )

        self.assertIs(resultado, usuario)
        buscar_usuario.assert_called_once_with(
            correo="usuario@example.com",
        )
