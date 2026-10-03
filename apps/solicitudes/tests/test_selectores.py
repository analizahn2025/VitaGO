import uuid
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.solicitudes.selectores import listar_solicitudes_autorizadas
from apps.usuarios.models import Usuario
from apps.usuarios.servicios.permisos import AlcancesPermiso


class PruebasSelectoresSolicitudes(SimpleTestCase):
    def setUp(self):
        self.usuario = Usuario(
            id=uuid.uuid4(),
            correo="usuario@empresa.test",
            nombres="Usuario",
            apellidos="Prueba",
        )

    @patch("apps.solicitudes.selectores._consulta_base_solicitudes")
    @patch("apps.solicitudes.selectores.obtener_alcances_permiso")
    def test_permiso_global_no_restringe_el_listado(
        self,
        obtener_alcances,
        consulta_base,
    ):
        obtener_alcances.side_effect = [
            AlcancesPermiso(global_=True),
            AlcancesPermiso(),
            AlcancesPermiso(),
        ]
        consulta = MagicMock()
        consulta_base.return_value = consulta
        consulta.filter.return_value.distinct.return_value.order_by.return_value = (
            "consulta-global"
        )

        resultado = listar_solicitudes_autorizadas(self.usuario)

        filtro = consulta.filter.call_args.args[0]
        self.assertFalse(filtro.children)
        self.assertEqual(resultado, "consulta-global")

    @patch("apps.solicitudes.selectores._consulta_base_solicitudes")
    @patch("apps.solicitudes.selectores.obtener_alcances_permiso")
    def test_solicitante_global_solo_consulta_sus_propias_solicitudes(
        self,
        obtener_alcances,
        consulta_base,
    ):
        obtener_alcances.side_effect = [
            AlcancesPermiso(),
            AlcancesPermiso(global_=True),
            AlcancesPermiso(),
        ]
        consulta = MagicMock()
        consulta_base.return_value = consulta
        consulta.filter.return_value.distinct.return_value.order_by.return_value = (
            "consulta-propia"
        )

        resultado = listar_solicitudes_autorizadas(self.usuario)

        filtro = consulta.filter.call_args.args[0]
        self.assertIn("solicitada_por_id", str(filtro))
        self.assertIn(str(self.usuario.pk), str(filtro))
        self.assertEqual(resultado, "consulta-propia")
