"""Cupos individuales con configuración por empresa o general de la red."""

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.flota.models import Vehiculo
from apps.organizaciones.limites import configurar_limites_empresa, configurar_limites_red
from apps.organizaciones.models import Empresa, HistorialLimitesMotoristas, LimitesMotoristasRed, Sucursal
from apps.organizaciones.serializadores import SerializadorEmpresa
from apps.repartidores.limites import obtener_limites_repartidor
from apps.repartidores.models import Repartidor
from apps.repartidores.selectores import listar_repartidores_disponibles
from apps.repartidores.tests import test_cupo_tubos as datos_cupo
from apps.solicitudes.excepciones import CupoTubosInsuficiente, LimiteSolicitudesRepartidor
from apps.solicitudes.servicios import asignar_solicitud_manualmente
from apps.solicitudes.tests import test_asignaciones as datos
from apps.usuarios.models import Permiso, PermisoRol, Rol, RolUsuario, Usuario


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasLimitesCompartidos(TestCase):
    setUpTestData = classmethod(datos.PruebasAsignacionesSolicitud.setUpTestData.__func__)
    setUp = datos.PruebasAsignacionesSolicitud.setUp
    _registrar_gps = datos.PruebasAsignacionesSolicitud._registrar_gps
    _nueva = datos_cupo.PruebasCupoTubos._nueva
    _asignar = datos_cupo.PruebasCupoTubos._asignar
    _perfil = datos_cupo.PruebasCupoTubos._perfil

    def _cliente(self, usuario=None):
        cliente = APIClient()
        cliente.force_authenticate(usuario or self.administrador)
        return cliente

    def _empresa_url(self, empresa=None):
        return reverse("organizaciones:limites-motoristas-empresa", args=[(empresa or self.empresa).pk])

    def _red_url(self):
        return reverse("organizaciones:limites-motoristas-red")

    def _preparar_red(self):
        for r in self.repartidores:
            Repartidor.objects.filter(pk=r.pk).update(empresa=None)
            Usuario.objetos.filter(pk=r.usuario_id).update(empresa=None)
            Vehiculo.objects.filter(pk=r.vehiculo_id).update(empresa=None)
            RolUsuario.objetos.filter(usuario_id=r.usuario_id).update(activo=False, revocado_en=timezone.now())
            RolUsuario.objetos.create(
                usuario_id=r.usuario_id, rol=Rol.objetos.get(codigo="REPARTIDOR_RED"),
                tipo_alcance="GLOBAL", asignado_por=self.administrador,
            )

    def test_cupo_individual_no_es_un_fondo_compartido_entre_motoristas(self):
        configurar_limites_empresa(self.administrador, self.empresa.pk, {"limite_tubos": 10, "limite_solicitudes": 2})
        for r in self.repartidores:
            self._asignar(5, r)
            self._asignar(5, r)
            perfil = self._perfil(r)
            self.assertEqual((perfil["limite_tubos"], perfil["tubos_comprometidos"], perfil["solicitudes_activas"]), (10, 10, 2))
            self.assertEqual(perfil["capacidad"], "FULL")
        with self.assertRaises(LimiteSolicitudesRepartidor):
            self._asignar(1)

    def test_configurar_empresa_no_modifica_los_limites_de_otra(self):
        otra = Empresa.objects.create(nombre="Otra empresa", pais=self.pais)
        configurar_limites_empresa(self.administrador, self.empresa.pk, {"limite_tubos": 30})
        otra.refresh_from_db()
        self.assertEqual(otra.limite_tubos_por_motorista, 20)

    def test_valor_individual_anterior_no_es_autoridad(self):
        Repartidor.objects.filter(pk=self.repartidores[0].pk).update(limite_tubos=1)
        self._asignar(18)
        self.assertEqual(self._perfil()["limite_tubos"], 20)
        self.assertTrue(listar_repartidores_disponibles(self.administrador, {"cantidad_tubos": 2}).filter(pk=self.repartidores[0].pk).exists())

    def test_no_reduce_solicitudes_por_debajo_de_la_carga_actual(self):
        self._asignar(1)
        self._asignar(1)
        with self.assertRaises(ValidationError) as error:
            configurar_limites_empresa(self.administrador, self.empresa.pk, {"limite_solicitudes": 1})
        self.assertIn("limite_solicitudes", error.exception.detail)
        self.assertFalse(HistorialLimitesMotoristas.objects.exists())

    def test_no_reduce_tubos_si_hay_carga_desconocida(self):
        self._nueva(None, self.repartidores[0], "PICKED_UP")
        with self.assertRaises(ValidationError) as error:
            configurar_limites_empresa(self.administrador, self.empresa.pk, {"limite_tubos": 19})
        self.assertIn("limite_tubos", error.exception.detail)

    def test_aumentar_limite_reintenta_pendientes_despues_del_commit(self):
        Repartidor.objects.filter(pk=self.repartidores[1].pk).update(estado_operativo="OFFLINE")
        configurar_limites_empresa(self.administrador, self.empresa.pk, {"limite_tubos": 18})
        self._asignar(18)
        pendiente = self.solicitud
        pendiente.cantidad_tubos = 2
        pendiente.save(update_fields=("cantidad_tubos",))
        with self.captureOnCommitCallbacks(execute=True):
            configurar_limites_empresa(self.administrador, self.empresa.pk, {"limite_tubos": 20})
        pendiente.refresh_from_db()
        self.assertEqual(pendiente.repartidor_asignado_id, self.repartidores[0].pk)

    def test_repetir_mismos_valores_no_duplica_historial(self):
        datos = {"limite_tubos": 25, "motivo": "Contenedores de prueba"}
        configurar_limites_empresa(self.administrador, self.empresa.pk, datos)
        configurar_limites_empresa(self.administrador, self.empresa.pk, datos)
        historial = HistorialLimitesMotoristas.objects.get()
        self.assertEqual(historial.limites_anteriores["limite_tubos"], 20)
        self.assertEqual(historial.limites_nuevos["limite_tubos"], 25)
        self.assertEqual(historial.realizado_por, self.administrador)

    def test_api_empresa_y_listado_informan_limites_y_alcance(self):
        cliente = self._cliente()
        respuesta = cliente.patch(self._empresa_url(), {"limite_tubos": 25, "limite_solicitudes": 3}, format="json")
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertEqual(respuesta.data["alcance"], "EMPRESA")
        self.assertEqual(respuesta.data["limite_solicitudes"], 3)
        detalle = cliente.get(reverse("organizaciones:detalle-empresa", args=[self.empresa.pk]))
        self.assertEqual(detalle.data["limites_motoristas"], {"alcance": "EMPRESA", "limite_tubos": 25, "limite_solicitudes": 3})

    def test_api_no_acepta_campos_o_limites_invalidos(self):
        cliente = self._cliente()
        for datos in ({}, {"limite_tubos": 0}, {"limite_tubos": True}, {"limite_tubos": 1.5}, {"limite_solicitudes": 6}, {"capacidad": "FULL"}):
            with self.subTest(datos=datos):
                respuesta = cliente.patch(self._empresa_url(), datos, format="json")
                self.assertEqual(respuesta.status_code, 400, respuesta.data)
        self.assertFalse(HistorialLimitesMotoristas.objects.exists())

    def test_motorista_no_modifica_configuracion_empresa(self):
        respuesta = self._cliente(self.repartidores[0].usuario).patch(self._empresa_url(), {"limite_tubos": 30}, format="json")
        self.assertEqual(respuesta.status_code, 403)

    def test_permiso_de_sucursal_no_configura_toda_la_empresa(self):
        sucursal = Sucursal.objects.create(empresa=self.empresa, nombre="Sucursal", ubicacion=self.origen)
        usuario = Usuario.objetos.create(correo="administrador.sucursal@limites.test", nombres="Admin", apellidos="Sucursal", empresa=self.empresa)
        rol = Rol.objetos.create(codigo="PRUEBA_LIMITES_SUCURSAL", nombre="Administración local de prueba", permite_alcance_sucursal=True)
        PermisoRol.objetos.create(rol=rol, permiso=Permiso.objetos.get(codigo="empresa.administrar"))
        RolUsuario.objetos.create(usuario=usuario, rol=rol, tipo_alcance="SUCURSAL", empresa=self.empresa, sucursal=sucursal, asignado_por=self.administrador)
        respuesta = self._cliente(usuario).patch(self._empresa_url(), {"limite_tubos": 30}, format="json")
        self.assertEqual(respuesta.status_code, 404)

    def test_configuracion_de_red_no_esta_disponible_en_corporate(self):
        self.assertEqual(self._cliente().get(self._red_url()).status_code, 404)

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_red_tiene_un_solo_limite_para_todos_los_clientes_y_motoristas(self):
        self._preparar_red()
        otra = Empresa.objects.create(nombre="Otra cliente", pais=self.pais, limite_tubos_por_motorista=3)
        configurar_limites_red(self.administrador, {"limite_tubos": 25, "limite_solicitudes": 3})
        self._asignar(18)
        solicitud = self._nueva(7)
        solicitud.empresa = otra
        solicitud.save(update_fields=("empresa",))
        asignar_solicitud_manualmente(self.administrador, solicitud.pk, {"repartidor_id": self.repartidores[0].pk})
        self.assertEqual(self._perfil()["tubos_comprometidos"], 25)
        for r in self.repartidores:
            self.assertEqual(obtener_limites_repartidor(Repartidor.objects.get(pk=r.pk)), {"limite_tubos": 25, "limite_solicitudes": 3})
        self.assertEqual(HistorialLimitesMotoristas.objects.get().empresa_id, None)

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_red_rechaza_pedido_que_supera_cupo_total_de_varios_clientes(self):
        self._preparar_red()
        configurar_limites_red(self.administrador, {"limite_tubos": 19})
        self._asignar(18)
        with self.assertRaises(CupoTubosInsuficiente):
            self._asignar(2)
        self.assertFalse(listar_repartidores_disponibles(self.administrador, {"cantidad_tubos": 2}).filter(pk=self.repartidores[0].pk).exists())

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_red_no_permite_limites_independientes_por_cliente(self):
        cliente = self._cliente()
        respuesta = cliente.patch(self._empresa_url(), {"limite_tubos": 50}, format="json")
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn(self._red_url(), str(respuesta.data["detail"]))
        globales = cliente.patch(self._red_url(), {"limite_tubos": 30}, format="json")
        self.assertEqual(globales.status_code, 200, globales.data)
        empresa = cliente.get(self._empresa_url())
        self.assertEqual((empresa.data["alcance"], empresa.data["limite_tubos"]), ("RED", 30))

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_administrador_cliente_no_modifica_configuracion_global(self):
        usuario = Usuario.objetos.create(correo="admin.cliente@limites.test", nombres="Admin", apellidos="Cliente", empresa=self.empresa)
        RolUsuario.objetos.create(usuario=usuario, rol=Rol.objetos.get(codigo="ADMINISTRADOR_EMPRESA_EXTERNA"), tipo_alcance="EMPRESA", empresa=self.empresa, asignado_por=self.administrador)
        respuesta = self._cliente(usuario).patch(self._red_url(), {"limite_tubos": 30}, format="json")
        self.assertEqual(respuesta.status_code, 403)

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_listado_de_empresas_lee_configuracion_general_una_sola_vez(self):
        for indice in range(8):
            Empresa.objects.create(nombre=f"Cliente {indice}", pais=self.pais)
        with CaptureQueriesContext(connection) as consultas:
            resultado = SerializadorEmpresa(Empresa.objects.select_related("pais"), many=True).data
        self.assertEqual(len(resultado), 9)
        self.assertEqual(len(consultas), 2)

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_get_de_red_no_crea_configuracion_si_falta(self):
        # Solo datos aislados de prueba: se prueba la ausencia sin INSERT en GET.
        LimitesMotoristasRed.objects.all().delete()
        respuesta = self._cliente().get(self._red_url())
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data["limite_tubos"], 20)
        self.assertFalse(LimitesMotoristasRed.objects.exists())
