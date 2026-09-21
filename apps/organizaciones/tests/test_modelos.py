from django.test import SimpleTestCase

from apps.organizaciones.opciones import EstadoOrganizacion
from apps.organizaciones.models import Empresa


class PruebasModeloEmpresa(SimpleTestCase):
    def test_empresa_esta_activa_por_defecto(self):
        empresa = Empresa(nombre="VitaGo")

        self.assertEqual(empresa.estado, EstadoOrganizacion.ACTIVO)
