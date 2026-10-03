import uuid
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.ubicaciones.serializadores import SerializadorCreacionUbicacion
from apps.ubicaciones.vistas import (
    VistaAutorizacionUbicacionEmpresa,
    VistaListaCreacionUbicaciones,
)
from apps.usuarios.models import Usuario


class PruebasAPIAdministracionUbicaciones(SimpleTestCase):
    def setUp(self):
        self.fabrica = APIRequestFactory()
        self.usuario = Usuario(
            id=uuid.uuid4(),
            correo="administrador@empresa.test",
            nombres="Ana",
            apellidos="Administradora",
        )

    def _datos_ubicacion(self, **cambios):
        datos = {
            "empresa_id": str(uuid.uuid4()),
            "nombre": "Clínica Central",
            "tipo_ubicacion_id": str(uuid.uuid4()),
            "origen": "REGISTRADA_USUARIO",
            "pais_id": str(uuid.uuid4()),
            "departamento": "Francisco Morazán",
            "municipio": "Distrito Central",
            "ciudad": "Tegucigalpa",
            "colonia": "Colonia Palmira",
            "direccion": "Dirección de prueba",
            "latitud": "14.072300",
            "longitud": "-87.192100",
            "permite_origen": True,
            "permite_destino": True,
        }
        datos.update(cambios)
        return datos

    @patch("apps.ubicaciones.vistas.SerializadorRelacionUbicacionEmpresa")
    @patch("apps.ubicaciones.vistas.registrar_ubicacion")
    def test_creacion_delega_en_servicio_autorizado(
        self,
        registrar,
        serializador_salida,
    ):
        registrar.return_value = MagicMock()
        serializador_salida.return_value.data = {"id": str(uuid.uuid4())}
        solicitud = self.fabrica.post(
            reverse("ubicaciones:lista-creacion-ubicaciones"),
            self._datos_ubicacion(),
            format="json",
        )
        force_authenticate(solicitud, user=self.usuario)

        respuesta = VistaListaCreacionUbicaciones.as_view()(solicitud)

        self.assertEqual(respuesta.status_code, 201)
        registrar.assert_called_once()

    @patch("apps.ubicaciones.vistas.registrar_ubicacion")
    def test_sin_permiso_responde_403(self, registrar):
        registrar.side_effect = PermissionDenied(
            'No tiene el permiso requerido: "ubicacion.crear".'
        )
        solicitud = self.fabrica.post(
            reverse("ubicaciones:lista-creacion-ubicaciones"),
            self._datos_ubicacion(),
            format="json",
        )
        force_authenticate(solicitud, user=self.usuario)

        respuesta = VistaListaCreacionUbicaciones.as_view()(solicitud)

        self.assertEqual(respuesta.status_code, 403)

    def test_google_exige_identificador_de_lugar(self):
        serializador = SerializadorCreacionUbicacion(
            data=self._datos_ubicacion(origen="GOOGLE")
        )

        self.assertFalse(serializador.is_valid())
        self.assertIn("identificador_lugar_google", serializador.errors)

    def test_registro_manual_rechaza_identificador_google(self):
        serializador = SerializadorCreacionUbicacion(
            data=self._datos_ubicacion(
                identificador_lugar_google="place-id-no-valido"
            )
        )

        self.assertFalse(serializador.is_valid())
        self.assertIn("identificador_lugar_google", serializador.errors)

    def test_nombres_geograficos_se_mapean_al_modelo(self):
        serializador = SerializadorCreacionUbicacion(
            data=self._datos_ubicacion()
        )

        self.assertTrue(serializador.is_valid(), serializador.errors)
        self.assertEqual(
            serializador.validated_data["nivel_administrativo_1"],
            "Francisco Morazán",
        )
        self.assertEqual(
            serializador.validated_data["nivel_administrativo_2"],
            "Distrito Central",
        )
        self.assertEqual(
            serializador.validated_data["localidad"],
            "Tegucigalpa",
        )
        self.assertEqual(
            serializador.validated_data["colonia"],
            "Colonia Palmira",
        )

    @patch("apps.ubicaciones.vistas.SerializadorRelacionUbicacionEmpresa")
    @patch("apps.ubicaciones.vistas.actualizar_autorizacion_ubicacion")
    def test_actualizacion_de_autorizacion_usa_servicio(
        self,
        actualizar,
        serializador_salida,
    ):
        actualizar.return_value = MagicMock()
        serializador_salida.return_value.data = {"estado": "APROBADO"}
        ubicacion_id = uuid.uuid4()
        empresa_id = uuid.uuid4()
        solicitud = self.fabrica.patch(
            reverse(
                "ubicaciones:autorizacion-empresa",
                kwargs={
                    "ubicacion_id": ubicacion_id,
                    "empresa_id": empresa_id,
                },
            ),
            {"estado": "APROBADO", "permite_origen": True},
            format="json",
        )
        force_authenticate(solicitud, user=self.usuario)

        respuesta = VistaAutorizacionUbicacionEmpresa.as_view()(
            solicitud,
            ubicacion_id=ubicacion_id,
            empresa_id=empresa_id,
        )

        self.assertEqual(respuesta.status_code, 200)
        actualizar.assert_called_once()
