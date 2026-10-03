import uuid
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.solicitudes.excepciones import CreacionSolicitudNoDisponible
from apps.solicitudes.models import Solicitud, TipoServicio
from apps.solicitudes.serializadores import SerializadorCreacionSolicitud
from apps.solicitudes.servicios import crear_solicitud
from apps.solicitudes.vistas import (
    VistaDetalleSolicitud,
    VistaListaCreacionSolicitudes,
    VistaListaTiposServicio,
)
from apps.usuarios.models import Usuario


class PruebasAPISolicitudes(SimpleTestCase):
    def setUp(self):
        self.fabrica = APIRequestFactory()
        self.usuario = Usuario(
            id=uuid.uuid4(),
            correo="solicitante@empresa.test",
            nombres="Sofía",
            apellidos="Solicitante",
        )

    def _datos_creacion(self, **cambios):
        datos = {
            "empresa_id": str(uuid.uuid4()),
            "prioridad": "NORMAL",
            "tipo_servicio_id": str(uuid.uuid4()),
            "origen_id": str(uuid.uuid4()),
            "destino_id": str(uuid.uuid4()),
            "articulos": [
                {
                    "tipo_articulo": "Muestra de laboratorio",
                    "cantidad": "1.00",
                    "codigo_referencia": "REF-001",
                }
            ],
        }
        datos.update(cambios)
        return datos

    def test_catalogo_requiere_autenticacion(self):
        respuesta = self.client.get(reverse("solicitudes:tipos-servicio"))

        self.assertEqual(respuesta.status_code, 401)

    @patch("apps.solicitudes.vistas.listar_tipos_servicio_autorizados")
    def test_catalogo_devuelve_resultados_sin_paginacion(self, listar_tipos):
        listar_tipos.return_value = [
            TipoServicio(
                id=uuid.uuid4(),
                codigo="MEDICAMENTO",
                nombre="Medicamento",
                descripcion="Traslado de medicamentos.",
            )
        ]
        solicitud = self.fabrica.get(reverse("solicitudes:tipos-servicio"))
        force_authenticate(solicitud, user=self.usuario)

        respuesta = VistaListaTiposServicio.as_view()(solicitud)

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            respuesta.data["resultados"][0]["codigo"],
            "MEDICAMENTO",
        )

    @patch("apps.solicitudes.vistas.SerializadorSolicitudDetalle")
    @patch("apps.solicitudes.vistas.crear_solicitud")
    def test_creacion_delega_en_servicio_atomico(
        self,
        crear,
        serializador_salida,
    ):
        creada = MagicMock(spec=Solicitud)
        crear.return_value = creada
        serializador_salida.return_value.data = {
            "id": str(uuid.uuid4()),
            "estado": "PENDING",
        }
        solicitud = self.fabrica.post(
            reverse("solicitudes:lista-creacion"),
            self._datos_creacion(),
            format="json",
        )
        force_authenticate(solicitud, user=self.usuario)

        respuesta = VistaListaCreacionSolicitudes.as_view()(solicitud)

        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual(respuesta.data["estado"], "PENDING")
        crear.assert_called_once()

    @patch("apps.solicitudes.vistas.SerializadorSolicitudDetalle")
    @patch("apps.solicitudes.vistas.obtener_solicitud_autorizada")
    def test_detalle_usa_selector_autorizado(
        self,
        obtener,
        serializador_salida,
    ):
        solicitud_id = uuid.uuid4()
        solicitud_objeto = MagicMock(spec=Solicitud)
        obtener.return_value = solicitud_objeto
        serializador_salida.return_value.data = {"id": str(solicitud_id)}
        solicitud = self.fabrica.get(
            reverse(
                "solicitudes:detalle",
                kwargs={"solicitud_id": solicitud_id},
            )
        )
        force_authenticate(solicitud, user=self.usuario)

        respuesta = VistaDetalleSolicitud.as_view()(
            solicitud,
            solicitud_id=solicitud_id,
        )

        self.assertEqual(respuesta.status_code, 200)
        obtener.assert_called_once_with(self.usuario, solicitud_id)

    def test_creacion_exige_al_menos_un_articulo(self):
        serializador = SerializadorCreacionSolicitud(
            data=self._datos_creacion(articulos=[])
        )

        self.assertFalse(serializador.is_valid())
        self.assertIn("articulos", serializador.errors)

    def test_creacion_rechaza_cantidad_no_positiva(self):
        serializador = SerializadorCreacionSolicitud(
            data=self._datos_creacion(
                articulos=[
                    {
                        "tipo_articulo": "Documento",
                        "cantidad": "0",
                    }
                ]
            )
        )

        self.assertFalse(serializador.is_valid())
        self.assertIn("articulos", serializador.errors)

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_bloquea_creacion_hasta_tener_cotizacion(self):
        with self.assertRaises(CreacionSolicitudNoDisponible):
            crear_solicitud.__wrapped__(self.usuario, {})
