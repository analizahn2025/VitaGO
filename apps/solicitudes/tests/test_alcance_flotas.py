"""Corporate exclusivo por empresa; Network global sin mezclar datos de clientes."""

from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.exceptions import ValidationError

from apps.flota.models import Vehiculo
from apps.organizaciones.models import Empresa
from apps.repartidores.models import Repartidor
from apps.seguimiento.models import RegistroUbicacion
from apps.solicitudes.asignacion_automatica import candidatos_ordenados
from apps.solicitudes.excepciones import LimiteSolicitudesRepartidor
from apps.solicitudes.models import Solicitud
from apps.solicitudes.selectores import listar_solicitudes_autorizadas
from apps.solicitudes.servicios import asignar_solicitud_manualmente
from apps.solicitudes.tests import test_asignaciones as datos
from apps.usuarios.models import Rol, RolUsuario, Usuario


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasAlcanceFlotas(TestCase):
    setUpTestData = classmethod(datos.PruebasAsignacionesSolicitud.setUpTestData.__func__)
    _registrar_gps = datos.PruebasAsignacionesSolicitud._registrar_gps

    def setUp(self):
        datos.PruebasAsignacionesSolicitud.setUp(self)
        self.otra_empresa = Empresa.objects.create(nombre="Empresa cliente B", pais=self.pais)
        self.enterContext(patch("apps.rutas.proveedor_google.urlopen", side_effect=AssertionError("Sin Google real.")))

    def _motorista(self, empresa=None):
        usuario = Usuario.objetos.create(correo=f"flota{Usuario.objetos.count()}@prueba.test", nombres="Motorista", apellidos="Alcance", empresa=empresa)
        RolUsuario.objetos.create(usuario=usuario, rol=Rol.objetos.get(codigo="REPARTIDOR_CORPORATIVO" if empresa else "REPARTIDOR_RED"), tipo_alcance="EMPRESA" if empresa else "GLOBAL", empresa=empresa, asignado_por=self.administrador)
        vehiculo = Vehiculo.objects.create(empresa=empresa, placa=f"ALC-{Vehiculo.objects.count()}", tipo="MOTOCICLETA")
        motorista = Repartidor.objects.create(usuario=usuario, empresa=empresa, vehiculo=vehiculo, estado_operativo="AVAILABLE")
        self._registrar_gps(motorista, str(self.origen.latitud), str(self.origen.longitud))
        return motorista

    def _solicitud(self, empresa):
        return Solicitud.objects.create(cantidad_tubos=1, numero=f"SOL-ALCANCE-{Solicitud.objects.count()}", empresa=empresa, solicitada_por=self.administrador, prioridad="NORMAL", tipo_servicio=self.tipo_servicio, origen=self.origen, destino=self.destino)

    def test_corporate_candidatos_solo_de_la_empresa_aunque_otro_este_mas_cerca(self):
        RegistroUbicacion.objects.filter(repartidor_id__in=[r.pk for r in self.repartidores]).update(latitud="15.000000")
        self._motorista(self.otra_empresa)
        self._motorista()
        self.assertEqual({pk for pk, _ in candidatos_ordenados(self.solicitud)}, {r.pk for r in self.repartidores})

    def test_corporate_no_asigna_motorista_de_otra_empresa(self):
        otro = self._motorista(self.otra_empresa)
        with self.assertRaises(ValidationError) as error:
            asignar_solicitud_manualmente(self.administrador, self.solicitud.pk, {"repartidor_id": otro.pk})
        self.assertIn("repartidor_id", error.exception.detail)

    def test_corporate_no_usa_motorista_global_de_network(self):
        global_ = self._motorista()
        with self.assertRaises(ValidationError):
            asignar_solicitud_manualmente(self.administrador, self.solicitud.pk, {"repartidor_id": global_.pk})

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_no_admite_motorista_vinculado_a_empresa(self):
        with self.assertRaises(ValidationError) as error:
            asignar_solicitud_manualmente(self.administrador, self.solicitud.pk, {"repartidor_id": self.repartidores[0].pk})
        self.assertIn("repartidor_id", error.exception.detail)

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_mismo_candidato_global_para_empresas_distintas(self):
        global_ = self._motorista()
        self._motorista(self.otra_empresa)
        for solicitud in (self.solicitud, self._solicitud(self.otra_empresa)):
            self.assertEqual([pk for pk, _ in candidatos_ordenados(solicitud)], [global_.pk])

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_asigna_global_a_dos_empresas_sin_vincularlo_a_ninguna(self):
        global_ = self._motorista()
        for solicitud in (self.solicitud, self._solicitud(self.otra_empresa)):
            asignar_solicitud_manualmente(self.administrador, solicitud.pk, {"repartidor_id": global_.pk})
            solicitud.refresh_from_db()
            self.assertEqual(solicitud.repartidor_asignado_id, global_.pk)
        global_.refresh_from_db()
        self.assertIsNone(global_.empresa_id)
        self.assertIsNone(global_.usuario.empresa_id)

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_cupo_cinco_es_total_no_cinco_por_empresa(self):
        global_ = self._motorista()
        solicitudes = [self.solicitud] + [self._solicitud(self.otra_empresa if i % 2 else self.empresa) for i in range(5)]
        for solicitud in solicitudes[:5]:
            asignar_solicitud_manualmente(self.administrador, solicitud.pk, {"repartidor_id": global_.pk})
        with self.assertRaises(LimiteSolicitudesRepartidor):
            asignar_solicitud_manualmente(self.administrador, solicitudes[-1].pk, {"repartidor_id": global_.pk})
        self.assertEqual(candidatos_ordenados(solicitudes[-1]), [])

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_empresas_network_no_ven_solicitudes_ajenas_aunque_compartan_motorista(self):
        global_ = self._motorista()
        solicitudes = [self.solicitud, self._solicitud(self.otra_empresa)]
        for solicitud in solicitudes:
            asignar_solicitud_manualmente(self.administrador, solicitud.pk, {"repartidor_id": global_.pk})
        for indice, empresa in enumerate((self.empresa, self.otra_empresa)):
            cliente = Usuario.objetos.create(correo=f"cliente{indice}@prueba.test", nombres="Cliente", apellidos="Empresa", empresa=empresa)
            RolUsuario.objetos.create(usuario=cliente, rol=Rol.objetos.get(codigo="ADMINISTRADOR_EMPRESA_EXTERNA"), tipo_alcance="EMPRESA", empresa=empresa, asignado_por=self.administrador)
            visibles = set(listar_solicitudes_autorizadas(cliente).values_list("pk", flat=True))
            self.assertEqual(visibles, {solicitudes[indice].pk})
