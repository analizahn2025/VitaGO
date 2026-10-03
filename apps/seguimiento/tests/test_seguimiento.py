import uuid
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.flota.models import Vehiculo
from apps.geografia.models import Pais
from apps.jornadas.models import JornadaRepartidor
from apps.organizaciones.models import Empresa
from apps.repartidores.models import Repartidor
from apps.repartidores.opciones import EstadoOperativoRepartidor
from apps.seguimiento.models import RegistroUbicacion
from apps.seguimiento.selectores import obtener_seguimiento_solicitud
from apps.seguimiento.servicios import registrar_ubicaciones
from apps.solicitudes.models import AsignacionSolicitud, Solicitud, TipoServicio
from apps.solicitudes.opciones import (
    EstadoAsignacionSolicitud,
    EstadoSolicitud,
    PrioridadSolicitud,
)
from apps.ubicaciones.models import TipoUbicacion, Ubicacion
from apps.ubicaciones.opciones import OrigenUbicacion
from apps.usuarios.models import Rol, RolUsuario, Usuario
from apps.usuarios.opciones import TipoAlcanceRol


@override_settings(
    MODO_APLICACION="CORPORATIVO",
    PROVEEDOR_AUTENTICACION="LOCAL",
)
class PruebasSeguimiento(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pais = Pais.objects.create(
            iso2="HN",
            iso3="HND",
            nombre="Honduras",
            codigo_telefonico="+504",
            codigo_moneda="HNL",
            zona_horaria_predeterminada="America/Tegucigalpa",
        )
        cls.empresa = Empresa.objects.create(nombre="Analiza", pais=cls.pais)
        cls.administrador = Usuario.objetos.create(
            correo="administrador.seguimiento@analiza.test",
            nombres="Administrador",
            apellidos="Seguimiento",
            empresa=cls.empresa,
            es_superusuario=True,
        )
        cls.solicitante = Usuario.objetos.create(
            correo="solicitante.seguimiento@analiza.test",
            nombres="Solicitante",
            apellidos="Seguimiento",
            empresa=cls.empresa,
        )
        cls.usuario_repartidor = Usuario.objetos.create(
            correo="motorista.seguimiento@analiza.test",
            nombres="Motorista",
            apellidos="Seguimiento",
            empresa=cls.empresa,
        )
        RolUsuario.objetos.create(
            usuario=cls.solicitante,
            rol=Rol.objetos.get(codigo="SOLICITANTE_CORPORATIVO"),
            tipo_alcance=TipoAlcanceRol.EMPRESA,
            empresa=cls.empresa,
            asignado_por=cls.administrador,
        )
        RolUsuario.objetos.create(
            usuario=cls.usuario_repartidor,
            rol=Rol.objetos.get(codigo="REPARTIDOR_CORPORATIVO"),
            tipo_alcance=TipoAlcanceRol.EMPRESA,
            empresa=cls.empresa,
            asignado_por=cls.administrador,
        )
        vehiculo = Vehiculo.objects.create(
            empresa=cls.empresa,
            placa="GPS-001",
            tipo="MOTOCICLETA",
        )
        cls.repartidor = Repartidor.objects.create(
            usuario=cls.usuario_repartidor,
            empresa=cls.empresa,
            vehiculo=vehiculo,
            estado_operativo=EstadoOperativoRepartidor.EN_RUTA,
        )
        tipo_ubicacion = TipoUbicacion.objects.create(
            codigo="PRUEBA_SEGUIMIENTO",
            nombre="Prueba de seguimiento",
        )
        cls.origen = Ubicacion.objects.create(
            nombre="Origen",
            tipo_ubicacion=tipo_ubicacion,
            origen=OrigenUbicacion.REGISTRADA_USUARIO,
            pais=cls.pais,
            direccion="Origen de prueba",
            latitud=Decimal("14.072300"),
            longitud=Decimal("-87.192100"),
        )
        cls.destino = Ubicacion.objects.create(
            nombre="Destino",
            tipo_ubicacion=tipo_ubicacion,
            origen=OrigenUbicacion.REGISTRADA_USUARIO,
            pais=cls.pais,
            direccion="Destino de prueba",
            latitud=Decimal("14.082300"),
            longitud=Decimal("-87.182100"),
        )
        cls.tipo_servicio = TipoServicio.objects.create(
            codigo="PRUEBA_SEGUIMIENTO",
            nombre="Prueba de seguimiento",
        )

    def setUp(self):
        self.ahora = timezone.now()
        self.jornada = JornadaRepartidor.objects.create(
            repartidor=self.repartidor,
            iniciada_en=self.ahora - timedelta(minutes=15),
        )
        self.solicitud = Solicitud.objects.create(
            numero=f"SOL-GPS-{uuid.uuid4().hex[:8]}",
            empresa=self.empresa,
            solicitada_por=self.solicitante,
            repartidor_asignado=self.repartidor,
            prioridad=PrioridadSolicitud.NORMAL,
            tipo_servicio=self.tipo_servicio,
            origen=self.origen,
            destino=self.destino,
            estado=EstadoSolicitud.HACIA_RECOLECCION,
            asignada_en=self.ahora - timedelta(minutes=10),
        )
        self.asignacion = AsignacionSolicitud.objects.create(
            solicitud=self.solicitud,
            repartidor=self.repartidor,
            asignada_por=self.administrador,
            estado=EstadoAsignacionSolicitud.ACTIVA,
            asignada_en=self.ahora - timedelta(minutes=10),
            aceptada_en=self.ahora - timedelta(minutes=5),
        )

    def _registro(self, registrada_en, identificador=None):
        return {
            "id_cliente": identificador or uuid.uuid4(),
            "latitud": Decimal("14.075000"),
            "longitud": Decimal("-87.190000"),
            "precision_metros": Decimal("8.50"),
            "velocidad_metros_segundo": Decimal("4.250"),
            "rumbo_grados": Decimal("180.00"),
            "registrada_en": registrada_en,
        }

    def test_clasifica_puntos_segun_intervalo_operativo(self):
        resultado = registrar_ubicaciones(
            self.usuario_repartidor,
            {
                "jornada_id": self.jornada.id,
                "registros": [
                    self._registro(self.ahora - timedelta(minutes=8)),
                    self._registro(self.ahora - timedelta(minutes=2)),
                ],
            },
        )

        self.assertEqual(resultado["creados"], 2)
        self.assertFalse(resultado["registros"][0].es_operativo)
        self.assertTrue(resultado["registros"][1].es_operativo)

    def test_reintento_idempotente_no_duplica(self):
        registro = self._registro(self.ahora - timedelta(minutes=2))
        datos = {"jornada_id": self.jornada.id, "registros": [registro]}

        registrar_ubicaciones(self.usuario_repartidor, datos)
        segundo_resultado = registrar_ubicaciones(self.usuario_repartidor, datos)

        self.assertEqual(RegistroUbicacion.objects.count(), 1)
        self.assertEqual(segundo_resultado["creados"], 0)
        self.assertEqual(segundo_resultado["repetidos"], 1)

    def test_rechaza_punto_fuera_de_la_jornada(self):
        with self.assertRaises(ValidationError):
            registrar_ubicaciones(
                self.usuario_repartidor,
                {
                    "jornada_id": self.jornada.id,
                    "registros": [
                        self._registro(self.ahora - timedelta(minutes=20))
                    ],
                },
            )

    def test_consulta_contextual_devuelve_ultimo_punto_operativo(self):
        resultado = registrar_ubicaciones(
            self.usuario_repartidor,
            {
                "jornada_id": self.jornada.id,
                "registros": [self._registro(self.ahora - timedelta(minutes=1))],
            },
        )

        seguimiento = obtener_seguimiento_solicitud(
            self.solicitante,
            self.solicitud.id,
        )

        self.assertTrue(seguimiento["seguimiento_disponible"])
        self.assertEqual(seguimiento["ubicacion"].id, resultado["registros"][0].id)

    def test_solicitud_terminal_no_expone_ubicacion(self):
        registrar_ubicaciones(
            self.usuario_repartidor,
            {
                "jornada_id": self.jornada.id,
                "registros": [self._registro(self.ahora - timedelta(minutes=1))],
            },
        )
        self.solicitud.estado = EstadoSolicitud.ENTREGADA
        self.solicitud.entregada_en = self.ahora
        self.solicitud.save(update_fields=("estado", "entregada_en", "actualizado_en"))

        seguimiento = obtener_seguimiento_solicitud(
            self.solicitante,
            self.solicitud.id,
        )

        self.assertFalse(seguimiento["seguimiento_disponible"])
        self.assertIsNone(seguimiento["ubicacion"])

    def test_api_registra_lote_y_consulta_seguimiento(self):
        cliente = APIClient()
        cliente.force_authenticate(self.usuario_repartidor)
        respuesta_registro = cliente.post(
            reverse("seguimiento:registros"),
            {
                "jornada_id": str(self.jornada.id),
                "registros": [
                    {
                        **self._registro(self.ahora - timedelta(minutes=1)),
                        "id_cliente": str(uuid.uuid4()),
                        "registrada_en": (
                            self.ahora - timedelta(minutes=1)
                        ).isoformat(),
                    }
                ],
            },
            format="json",
        )

        cliente.force_authenticate(self.solicitante)
        respuesta_seguimiento = cliente.get(
            reverse(
                "solicitudes:seguimiento",
                kwargs={"solicitud_id": self.solicitud.id},
            )
        )

        self.assertEqual(respuesta_registro.status_code, 201)
        self.assertEqual(respuesta_registro.data["creados"], 1)
        self.assertEqual(respuesta_seguimiento.status_code, 200)
        self.assertTrue(respuesta_seguimiento.data["seguimiento_disponible"])
        self.assertIsNotNone(respuesta_seguimiento.data["ubicacion"])

    def test_api_requiere_autenticacion(self):
        cliente = APIClient()

        respuesta = cliente.post(reverse("seguimiento:registros"), {}, format="json")

        self.assertEqual(respuesta.status_code, 401)
