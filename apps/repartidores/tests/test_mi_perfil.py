from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.flota.models import Vehiculo
from apps.geografia.models import Pais
from apps.organizaciones.models import Empresa
from apps.repartidores.models import Repartidor
from apps.usuarios.models import Rol, RolUsuario, Usuario
from apps.usuarios.opciones import TipoAlcanceRol


@override_settings(MODO_APLICACION="CORPORATIVO")
class PruebasMiPerfilMotorista(TestCase):
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
        empresa = Empresa.objects.create(nombre="Analiza", pais=pais)
        cls.usuario = Usuario.objetos.create_user(
            correo="motorista.perfil@analiza.test",
            password="ClaveSeguraDePrueba2026!",
            nombres="Motorista",
            apellidos="Prueba",
            empresa=empresa,
        )
        rol = Rol.objetos.get(codigo="REPARTIDOR_CORPORATIVO")
        RolUsuario.objetos.create(
            usuario=cls.usuario,
            rol=rol,
            tipo_alcance=TipoAlcanceRol.EMPRESA,
            empresa=empresa,
        )
        vehiculo = Vehiculo.objects.create(
            empresa=empresa,
            placa="TEST-PERFIL-01",
            tipo="MOTOCICLETA",
        )
        cls.repartidor = Repartidor.objects.create(
            usuario=cls.usuario,
            empresa=empresa,
            vehiculo=vehiculo,
        )
        cls.otro_usuario = Usuario.objetos.create_user(
            correo="solicitante.perfil@analiza.test",
            password="ClaveSeguraDePrueba2026!",
            nombres="Solicitante",
            apellidos="Prueba",
            empresa=empresa,
        )

    def test_requiere_autenticacion(self):
        respuesta = APIClient().get(reverse("repartidores:mi-perfil"))

        self.assertEqual(respuesta.status_code, 401)

    def test_devuelve_solo_perfil_propio_sin_permiso_de_listado(self):
        cliente = APIClient()
        cliente.force_authenticate(user=self.usuario)

        respuesta = cliente.get(reverse("repartidores:mi-perfil"))

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data["id"], str(self.repartidor.id))
        self.assertEqual(respuesta.data["usuario"]["id"], str(self.usuario.id))
        self.assertEqual(
            respuesta.data["vehiculo"]["id"],
            str(self.repartidor.vehiculo_id),
        )
        self.assertEqual(respuesta.data["estado_operativo"], "OFFLINE")
        self.assertEqual(respuesta.data["capacidad"], "EMPTY")

    def test_usuario_sin_perfil_no_puede_ver_motorista_ajeno(self):
        cliente = APIClient()
        cliente.force_authenticate(user=self.otro_usuario)

        respuesta = cliente.get(reverse("repartidores:mi-perfil"))

        self.assertEqual(respuesta.status_code, 404)

    def test_perfil_inactivo_no_se_expone(self):
        self.repartidor.activo = False
        self.repartidor.save(update_fields=("activo", "actualizado_en"))
        cliente = APIClient()
        cliente.force_authenticate(user=self.usuario)

        respuesta = cliente.get(reverse("repartidores:mi-perfil"))

        self.assertEqual(respuesta.status_code, 404)
