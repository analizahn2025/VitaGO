from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from apps.flota.models import Vehiculo
from apps.flota.opciones import TipoVehiculo
from apps.geografia.models import Pais
from apps.jornadas.models import JornadaRepartidor
from apps.organizaciones.models import Empresa, Sucursal
from apps.repartidores.models import Repartidor
from apps.repartidores.opciones import EstadoOperativoRepartidor
from apps.solicitudes.models import AsignacionSolicitud, Solicitud
from apps.solicitudes.opciones import EstadoSolicitud, ModalidadSolicitud
from apps.solicitudes.selectores import (
    listar_solicitudes_autorizadas,
    obtener_opciones_creacion_solicitud,
)
from apps.ubicaciones.models import Ubicacion, UbicacionEmpresa
from apps.usuarios.models import Rol, RolUsuario, Usuario
from apps.usuarios.opciones import TipoAlcanceRol


@override_settings(
    MODO_APLICACION="CORPORATIVO",
    PROVEEDOR_AUTENTICACION="LOCAL",
)
class PruebasDatosPruebaCorporativo(TestCase):
    @classmethod
    def setUpTestData(cls):
        pais = Pais.objects.create(
            iso2="HN",
            iso3="HND",
            nombre="Honduras",
            codigo_telefonico="+504",
            codigo_moneda="HNL",
            zona_horaria_predeterminada="America/Tegucigalpa",
        )
        cls.empresa = Empresa.objects.create(nombre="Analiza", pais=pais)
        administrador = Usuario.objetos.create(
            correo="admin.escenario@analiza.test",
            nombres="Admin",
            apellidos="Prueba",
            es_superusuario=True,
        )
        cls.solicitante = Usuario.objetos.create(
            correo="solicitante.prueba@analiza.test",
            nombres="Solicitante",
            apellidos="Prueba",
            empresa=cls.empresa,
        )
        motorista = Usuario.objetos.create(
            correo="motorista.prueba@analiza.test",
            nombres="Motorista",
            apellidos="Prueba",
            empresa=cls.empresa,
        )
        for usuario, codigo_rol in (
            (cls.solicitante, "SOLICITANTE_CORPORATIVO"),
            (motorista, "REPARTIDOR_CORPORATIVO"),
        ):
            RolUsuario.objetos.create(
                usuario=usuario,
                rol=Rol.objetos.get(codigo=codigo_rol),
                tipo_alcance=TipoAlcanceRol.EMPRESA,
                empresa=cls.empresa,
                asignado_por=administrador,
            )
        vehiculo = Vehiculo.objects.create(
            empresa=cls.empresa,
            placa="ESCENARIO-PRUEBA",
            tipo=TipoVehiculo.MOTOCICLETA,
        )
        cls.repartidor = Repartidor.objects.create(
            usuario=motorista,
            empresa=cls.empresa,
            vehiculo=vehiculo,
            estado_operativo=EstadoOperativoRepartidor.DISPONIBLE,
        )
        JornadaRepartidor.objects.create(repartidor=cls.repartidor)

    @patch(
        "apps.nucleo.management.commands.crear_datos_prueba_corporativo."
        "Command._validar_entorno"
    )
    def test_crea_escenario_repetible_y_visible_segun_rol(self, _validar_entorno):
        call_command(
            "crear_datos_prueba_corporativo",
            "--confirmar",
            stdout=StringIO(),
        )
        self.repartidor.estado_operativo = EstadoOperativoRepartidor.EN_RUTA
        self.repartidor.save(update_fields=("estado_operativo", "actualizado_en"))
        call_command(
            "crear_datos_prueba_corporativo",
            "--confirmar",
            stdout=StringIO(),
        )

        self.assertEqual(Ubicacion.objects.count(), 3)
        self.assertEqual(UbicacionEmpresa.objects.count(), 3)
        self.assertEqual(Sucursal.objects.count(), 2)
        self.assertEqual(Solicitud.objects.count(), 2)
        self.assertEqual(AsignacionSolicitud.objects.count(), 2)
        self.assertEqual(
            set(Solicitud.objects.values_list("modalidad", "estado")),
            {
                (ModalidadSolicitud.ENTRE_SUCURSALES, EstadoSolicitud.ASIGNADA),
                (ModalidadSolicitud.EMPRESA_TRANSPORTE, EstadoSolicitud.ASIGNADA),
            },
        )

        origen = Ubicacion.objects.get(nombre="Prueba - Sucursal Centro")
        opciones = obtener_opciones_creacion_solicitud(
            self.solicitante,
            {
                "empresa_id": self.empresa.id,
                "modalidad": ModalidadSolicitud.ENTRE_SUCURSALES,
                "origen_id": origen.id,
            },
        )
        self.assertEqual(len(opciones["origenes"]), 2)
        self.assertEqual(len(opciones["destinos"]), 1)
        self.assertEqual(
            opciones["destinos"][0]["ubicacion"].nombre,
            "Prueba - Sucursal Norte",
        )
        self.assertEqual(
            listar_solicitudes_autorizadas(self.solicitante).count(), 2
        )
        self.assertEqual(
            listar_solicitudes_autorizadas(self.repartidor.usuario).count(), 2
        )


class PruebasProteccionComando(SimpleTestCase):
    def test_exige_confirmacion(self):
        with self.assertRaisesMessage(CommandError, "--confirmar"):
            call_command("crear_datos_prueba_corporativo", stdout=StringIO())

    @override_settings(DEBUG=False)
    def test_rechaza_entorno_no_local(self):
        with self.assertRaisesMessage(CommandError, "solo admite Corporate LOCAL"):
            call_command(
                "crear_datos_prueba_corporativo",
                "--confirmar",
                stdout=StringIO(),
            )
