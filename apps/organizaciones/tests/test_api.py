import uuid
from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.geografia.models import Pais
from apps.organizaciones.models import Empresa, Sucursal
from apps.organizaciones.vistas import (
    VistaDetalleEmpresa,
    VistaDetalleSucursal,
    VistaListaEmpresas,
    VistaListaSucursalesEmpresa,
)
from apps.ubicaciones.models import TipoUbicacion, Ubicacion
from apps.ubicaciones.opciones import OrigenUbicacion
from apps.usuarios.models import Usuario


class PruebasAPIOrganizaciones(SimpleTestCase):
    def setUp(self):
        self.fabrica = APIRequestFactory()
        self.usuario = Usuario(
            id=uuid.uuid4(),
            correo="administrador@example.com",
            nombres="Administrador",
            apellidos="Prueba",
        )
        self.pais = Pais(
            id=uuid.uuid4(),
            iso2="HN",
            iso3="HND",
            nombre="Honduras",
            codigo_telefonico="+504",
            codigo_moneda="HNL",
            zona_horaria_predeterminada="America/Tegucigalpa",
        )
        self.empresa = Empresa(
            id=uuid.uuid4(),
            nombre="Analiza",
            pais=self.pais,
        )
        tipo = TipoUbicacion(
            id=uuid.uuid4(),
            codigo="SUCURSAL",
            nombre="Sucursal",
        )
        ubicacion = Ubicacion(
            id=uuid.uuid4(),
            nombre="Sede principal",
            tipo_ubicacion=tipo,
            origen=OrigenUbicacion.REGISTRADA_USUARIO,
            pais=self.pais,
            direccion="Dirección de prueba",
            latitud=Decimal("14.072300"),
            longitud=Decimal("-87.192100"),
        )
        self.sucursal = Sucursal(
            id=uuid.uuid4(),
            empresa=self.empresa,
            nombre="Principal",
            ubicacion=ubicacion,
        )

    def test_lista_empresas_requiere_autenticacion(self):
        respuesta = self.client.get(reverse("organizaciones:lista-empresas"))

        self.assertEqual(respuesta.status_code, 401)
        self.assertEqual(respuesta["WWW-Authenticate"], "Bearer")

    @patch("apps.organizaciones.vistas.listar_empresas_autorizadas")
    def test_lista_empresas_usa_paginacion_en_espanol(self, listar_empresas):
        listar_empresas.return_value = [self.empresa]
        solicitud = self.fabrica.get(
            reverse("organizaciones:lista-empresas")
        )
        force_authenticate(solicitud, user=self.usuario)

        respuesta = VistaListaEmpresas.as_view()(solicitud)

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data["conteo"], 1)
        self.assertIsNone(respuesta.data["pagina_siguiente"])
        self.assertIsNone(respuesta.data["pagina_anterior"])
        self.assertEqual(
            respuesta.data["resultados"][0]["nombre"],
            "Analiza",
        )
        self.assertEqual(
            respuesta.data["resultados"][0]["pais"]["iso2"],
            "HN",
        )
        listar_empresas.assert_called_once_with(self.usuario)

    @patch("apps.organizaciones.vistas.listar_empresas_autorizadas")
    def test_lista_empresas_sin_permiso_responde_403(self, listar_empresas):
        listar_empresas.side_effect = PermissionDenied(
            'No tiene el permiso requerido: "empresa.ver".'
        )
        solicitud = self.fabrica.get(
            reverse("organizaciones:lista-empresas")
        )
        force_authenticate(solicitud, user=self.usuario)

        respuesta = VistaListaEmpresas.as_view()(solicitud)

        self.assertEqual(respuesta.status_code, 403)

    @patch("apps.organizaciones.vistas.obtener_empresa_autorizada")
    def test_detalle_empresa_devuelve_contrato(self, obtener_empresa):
        obtener_empresa.return_value = self.empresa
        solicitud = self.fabrica.get(
            reverse(
                "organizaciones:detalle-empresa",
                kwargs={"empresa_id": self.empresa.id},
            )
        )
        force_authenticate(solicitud, user=self.usuario)

        respuesta = VistaDetalleEmpresa.as_view()(
            solicitud,
            empresa_id=self.empresa.id,
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data["nombre"], "Analiza")
        self.assertEqual(respuesta.data["pais"]["codigo_moneda"], "HNL")

    @patch("apps.organizaciones.vistas.listar_sucursales_autorizadas")
    def test_lista_sucursales_puede_estar_vacia(self, listar_sucursales):
        listar_sucursales.return_value = self.empresa, []
        solicitud = self.fabrica.get(
            reverse(
                "organizaciones:lista-sucursales-empresa",
                kwargs={"empresa_id": self.empresa.id},
            )
        )
        force_authenticate(solicitud, user=self.usuario)

        respuesta = VistaListaSucursalesEmpresa.as_view()(
            solicitud,
            empresa_id=self.empresa.id,
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data["conteo"], 0)
        self.assertEqual(respuesta.data["resultados"], [])

    @patch("apps.organizaciones.vistas.obtener_sucursal_autorizada")
    def test_detalle_sucursal_incluye_ubicacion(self, obtener_sucursal):
        obtener_sucursal.return_value = self.sucursal
        solicitud = self.fabrica.get(
            reverse(
                "organizaciones:detalle-sucursal",
                kwargs={"sucursal_id": self.sucursal.id},
            )
        )
        force_authenticate(solicitud, user=self.usuario)

        respuesta = VistaDetalleSucursal.as_view()(
            solicitud,
            sucursal_id=self.sucursal.id,
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data["nombre"], "Principal")
        self.assertEqual(
            respuesta.data["ubicacion"]["nombre"],
            "Sede principal",
        )
        self.assertEqual(
            respuesta.data["ubicacion"]["latitud"],
            "14.072300",
        )
