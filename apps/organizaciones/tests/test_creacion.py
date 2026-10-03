import uuid
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.organizaciones.vistas import VistaListaSucursalesEmpresa
from apps.usuarios.models import Usuario


class PruebasAPICreacionSucursales(SimpleTestCase):
    def setUp(self):
        self.fabrica = APIRequestFactory()
        self.usuario = Usuario(
            id=uuid.uuid4(),
            correo="administrador@empresa.test",
            nombres="Ana",
            apellidos="Administradora",
        )

    @patch("apps.organizaciones.vistas.SerializadorSucursal")
    @patch("apps.organizaciones.vistas.crear_sucursal")
    def test_creacion_delega_en_servicio(
        self,
        servicio_creacion,
        serializador_salida,
    ):
        servicio_creacion.return_value = MagicMock()
        serializador_salida.return_value.data = {
            "id": str(uuid.uuid4()),
            "nombre": "Principal",
        }
        empresa_id = uuid.uuid4()
        solicitud = self.fabrica.post(
            reverse(
                "organizaciones:lista-sucursales-empresa",
                kwargs={"empresa_id": empresa_id},
            ),
            {
                "nombre": "Principal",
                "ubicacion_id": str(uuid.uuid4()),
            },
            format="json",
        )
        force_authenticate(solicitud, user=self.usuario)

        respuesta = VistaListaSucursalesEmpresa.as_view()(
            solicitud,
            empresa_id=empresa_id,
        )

        self.assertEqual(respuesta.status_code, 201)
        servicio_creacion.assert_called_once()
