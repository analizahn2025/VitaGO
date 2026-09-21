import uuid
from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from apps.autenticacion.excepciones import TokenRefrescoInvalido
from apps.autenticacion.opciones import MotivoRevocacionSesion
from apps.autenticacion.servicios.sesiones import (
    MetadatosSesion,
    renovar_sesion,
)
from apps.usuarios.models import Usuario


class PruebasRotacionSesiones(SimpleTestCase):
    def _sesion(self, revocado_en=None):
        usuario = Usuario(
            correo="externo@example.com",
            nombres="Usuario",
            apellidos="Externo",
        )
        return SimpleNamespace(
            id=uuid.uuid4(),
            usuario=usuario,
            usuario_id=usuario.id,
            familia=uuid.uuid4(),
            identificador_token="jti-prueba",
            identificador_dispositivo="dispositivo-1",
            direccion_ip="127.0.0.1",
            agente_usuario="Agente de prueba",
            expira_en=timezone.now() + timedelta(days=1),
            revocado_en=revocado_en,
        )

    def test_rotacion_revoca_sesion_anterior_y_crea_reemplazo(self):
        sesion = self._sesion()
        token = {
            "sesion_id": str(sesion.id),
            "familia": str(sesion.familia),
            "usuario_id": str(sesion.usuario_id),
            "jti": sesion.identificador_token,
        }
        resultado_nuevo = SimpleNamespace(sesion=SimpleNamespace(id=uuid.uuid4()))
        selector = Mock()
        selector.select_related.return_value.get.return_value = sesion
        actualizador = Mock()

        with patch(
            "apps.autenticacion.servicios.sesiones.validar_token_refresco",
            return_value=token,
        ), patch(
            "apps.autenticacion.servicios.sesiones."
            "calcular_hash_token_refresco",
            return_value="a" * 64,
        ), patch(
            "apps.autenticacion.servicios.sesiones.transaction.atomic",
            return_value=nullcontext(),
        ), patch(
            "apps.autenticacion.servicios.sesiones."
            "SesionAutenticacion.objetos.select_for_update",
            return_value=selector,
        ), patch(
            "apps.autenticacion.servicios.sesiones._crear_sesion",
            return_value=resultado_nuevo,
        ) as crear_reemplazo, patch(
            "apps.autenticacion.servicios.sesiones."
            "SesionAutenticacion.objetos.filter",
            return_value=actualizador,
        ):
            resultado = renovar_sesion("token", MetadatosSesion())

        self.assertIs(resultado, resultado_nuevo)
        crear_reemplazo.assert_called_once()
        self.assertEqual(
            actualizador.update.call_args.kwargs["motivo_revocacion"],
            MotivoRevocacionSesion.ROTACION,
        )
        self.assertEqual(
            actualizador.update.call_args.kwargs["reemplazada_por"],
            resultado_nuevo.sesion,
        )

    def test_reutilizacion_revoca_familia_activa(self):
        sesion = self._sesion(revocado_en=timezone.now())
        selector = Mock()
        selector.select_related.return_value.get.return_value = sesion

        with patch(
            "apps.autenticacion.servicios.sesiones.validar_token_refresco",
            return_value={},
        ), patch(
            "apps.autenticacion.servicios.sesiones."
            "calcular_hash_token_refresco",
            return_value="a" * 64,
        ), patch(
            "apps.autenticacion.servicios.sesiones.transaction.atomic",
            return_value=nullcontext(),
        ), patch(
            "apps.autenticacion.servicios.sesiones."
            "SesionAutenticacion.objetos.select_for_update",
            return_value=selector,
        ), patch(
            "apps.autenticacion.servicios.sesiones._revocar_sesiones_activas"
        ) as revocar_familia, self.assertRaises(TokenRefrescoInvalido):
            renovar_sesion("token-reutilizado", MetadatosSesion())

        revocar_familia.assert_called_once()
        self.assertEqual(
            revocar_familia.call_args.args[0],
            {"familia": sesion.familia},
        )
        self.assertEqual(
            revocar_familia.call_args.args[1],
            MotivoRevocacionSesion.REUTILIZACION_TOKEN,
        )
