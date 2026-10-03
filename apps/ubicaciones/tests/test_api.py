import uuid
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.geografia.models import Pais
from apps.ubicaciones.models import TipoUbicacion
from apps.ubicaciones.models import Ubicacion
from apps.ubicaciones.opciones import OrigenUbicacion
from apps.ubicaciones.serializadores import SerializadorUbicacionAdministrada
from apps.ubicaciones.vistas import VistaListaTiposUbicacion
from apps.usuarios.models import Usuario


class PruebasAPITiposUbicacion(SimpleTestCase):
    def setUp(self):
        self.usuario = Usuario(
            id=uuid.uuid4(),
            correo="administrador@example.com",
            nombres="Administrador",
            apellidos="Prueba",
        )

    def test_requiere_autenticacion(self):
        respuesta = self.client.get(reverse("ubicaciones:lista-tipos"))

        self.assertEqual(respuesta.status_code, 401)
        self.assertEqual(respuesta["WWW-Authenticate"], "Bearer")

    @patch("apps.ubicaciones.vistas.listar_tipos_ubicacion_autorizados")
    def test_devuelve_catalogo_sin_paginacion(self, listar_tipos):
        listar_tipos.return_value = [
            TipoUbicacion(
                id=uuid.uuid4(),
                codigo="HOSPITAL",
                nombre="Hospital",
            ),
            TipoUbicacion(
                id=uuid.uuid4(),
                codigo="SUCURSAL",
                nombre="Sucursal",
            ),
        ]
        solicitud = APIRequestFactory().get(
            reverse("ubicaciones:lista-tipos")
        )
        force_authenticate(solicitud, user=self.usuario)

        respuesta = VistaListaTiposUbicacion.as_view()(solicitud)

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            [tipo["codigo"] for tipo in respuesta.data["resultados"]],
            ["HOSPITAL", "SUCURSAL"],
        )
        listar_tipos.assert_called_once_with(self.usuario)

    @patch("apps.ubicaciones.vistas.listar_tipos_ubicacion_autorizados")
    def test_sin_permiso_responde_403(self, listar_tipos):
        listar_tipos.side_effect = PermissionDenied(
            'No tiene el permiso requerido: "ubicacion.ver".'
        )
        solicitud = APIRequestFactory().get(
            reverse("ubicaciones:lista-tipos")
        )
        force_authenticate(solicitud, user=self.usuario)

        respuesta = VistaListaTiposUbicacion.as_view()(solicitud)

        self.assertEqual(respuesta.status_code, 403)


class PruebasContratoUbicacion(SimpleTestCase):
    def test_salida_utiliza_nombres_geograficos_del_negocio(self):
        pais = Pais(
            id=uuid.uuid4(),
            iso2="HN",
            iso3="HND",
            nombre="Honduras",
            codigo_telefonico="+504",
            codigo_moneda="HNL",
            zona_horaria_predeterminada="America/Tegucigalpa",
        )
        tipo = TipoUbicacion(
            id=uuid.uuid4(),
            codigo="CLINICA",
            nombre="Clínica",
        )
        ubicacion = Ubicacion(
            id=uuid.uuid4(),
            nombre="Clínica Central",
            tipo_ubicacion=tipo,
            origen=OrigenUbicacion.REGISTRADA_USUARIO,
            pais=pais,
            nivel_administrativo_1="Francisco Morazán",
            nivel_administrativo_2="Distrito Central",
            localidad="Tegucigalpa",
            colonia="Colonia Palmira",
            direccion="Dirección de prueba",
            latitud="14.072300",
            longitud="-87.192100",
        )

        datos = SerializadorUbicacionAdministrada(ubicacion).data

        self.assertEqual(datos["departamento"], "Francisco Morazán")
        self.assertEqual(datos["municipio"], "Distrito Central")
        self.assertEqual(datos["ciudad"], "Tegucigalpa")
        self.assertEqual(datos["colonia"], "Colonia Palmira")
        self.assertNotIn("nivel_administrativo_1", datos)
        self.assertNotIn("nivel_administrativo_2", datos)
        self.assertNotIn("localidad", datos)
