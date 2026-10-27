"""Regresiones de disponibilidad y contingencias por pérdida del rol operativo."""

from unittest.mock import patch

from django.db import transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.flota.models import Vehiculo
from apps.notificaciones.models import NotificacionUsuario
from apps.organizaciones.models import Empresa
from apps.repartidores.capacidad import puede_recibir_solicitudes
from apps.repartidores.models import Repartidor
from apps.repartidores.selectores import (
    listar_repartidores_autorizados, listar_repartidores_disponibles,
)
from apps.repartidores.servicios import crear_repartidor
from apps.rutas.selectores import obtener_paradas_operativas
from apps.solicitudes.contingencias import procesar_cierre_diario, procesar_suspension
from apps.solicitudes.opciones import EstadoSolicitud
from apps.solicitudes.servicios import asignar_solicitud_manualmente, reintentar_solicitudes_pendientes
from apps.solicitudes.tests import test_asignaciones as datos_asignaciones
from apps.solicitudes.tests import test_contingencias as datos_contingencias
from apps.usuarios.models import Rol, RolUsuario, Usuario
from apps.usuarios.servicios import revocar_rol_usuario


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasHabilitacionOperativa(TestCase):
    setUpTestData = classmethod(datos_asignaciones.PruebasAsignacionesSolicitud.setUpTestData.__func__)
    _registrar_gps = datos_asignaciones.PruebasAsignacionesSolicitud._registrar_gps
    _asignar = datos_contingencias.PruebasContingenciasCorporativas._asignar

    def setUp(self):
        datos_contingencias.PruebasContingenciasCorporativas.setUp(self)

    def _rol_actual(self, repartidor=None):
        return RolUsuario.objetos.get(
            usuario_id=(repartidor or self.anterior).usuario_id,
            rol__codigo="REPARTIDOR_CORPORATIVO", activo=True, empresa=self.empresa,
        )

    def _revocar(self):
        with self.captureOnCommitCallbacks(execute=True):
            revocar_rol_usuario(self.administrador, self.anterior.usuario, self._rol_actual().pk)
        self.solicitud.refresh_from_db()

    def test_revocar_ultimo_rol_reasigna_recogida_y_conserva_entrega_directa(self):
        original = self._asignar(EstadoSolicitud.EN_TRANSITO)
        recogida = self.solicitud.recolectada_en
        self._revocar()
        self.assertEqual(self.solicitud.repartidor_asignado_id, self.nuevo.pk)
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.EN_TRANSITO)
        self.assertEqual(self.solicitud.recolectada_en, recogida)
        self.assertFalse(self.solicitud.reasignacion_pendiente)
        self.assertEqual([p["tipo"] for p in obtener_paradas_operativas(self.nuevo)], ["ENTREGA"])
        self.assertEqual(obtener_paradas_operativas(self.anterior), [])
        original.refresh_from_db()
        self.assertEqual(original.estado, "REASIGNADA")
        self.assertIn("rol operativo", original.motivo)
        self.anterior.refresh_from_db()
        self.assertEqual((self.anterior.capacidad, self.anterior.estado_operativo), ("EMPTY", "OUT_OF_SERVICE"))
        self.assertEqual(self.anterior.usuario.estado, "ACTIVO")
        evento = self.solicitud.eventos.get(tipo="REASIGNACION_PENDIENTE")
        self.assertEqual(evento.metadatos["causa"], "ROL_OPERATIVO_NO_VIGENTE")
        self.assertTrue(evento.metadatos["traspaso_fisico_fuera_app"])
        self.assertTrue(NotificacionUsuario.objects.filter(usuario=self.nuevo.usuario, tipo="SOLICITUD_REASIGNADA").exists())

    def test_revocacion_sin_reemplazo_conserva_fase_y_se_recupera_sin_duplicados(self):
        self._asignar(EstadoSolicitud.RECOLECTADA)
        Repartidor.objects.filter(pk=self.nuevo.pk).update(estado_operativo="PAUSED")
        self._revocar()
        self.assertIsNone(self.solicitud.repartidor_asignado_id)
        self.assertTrue(self.solicitud.reasignacion_pendiente)
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.RECOLECTADA)
        self.assertFalse(self.solicitud.asignaciones.filter(estado="ACTIVA").exists())
        Repartidor.objects.filter(pk=self.nuevo.pk).update(estado_operativo="AVAILABLE")
        self.assertEqual(reintentar_solicitudes_pendientes(self.empresa.pk), 1)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.repartidor_asignado_id, self.nuevo.pk)
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.RECOLECTADA)
        cantidad = self.solicitud.asignaciones.count()
        self.assertEqual(procesar_suspension(self.anterior.usuario_id), 0)
        self.assertEqual(reintentar_solicitudes_pendientes(self.empresa.pk), 0)
        self.assertEqual(self.solicitud.asignaciones.count(), cantidad)

    def test_revocacion_antes_de_recoger_reinicia_recoleccion(self):
        self._asignar(EstadoSolicitud.EN_RECOLECCION)
        self._revocar()
        self.assertEqual(self.solicitud.repartidor_asignado_id, self.nuevo.pk)
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.HACIA_RECOLECCION)
        self.assertIsNone(self.solicitud.llegada_recoleccion_en)

    def test_revocacion_en_especial_conserva_tramos_y_no_inventa_gps(self):
        self._asignar(EstadoSolicitud.RECOLECTADA, especial=True)
        self._revocar()
        tramos = list(self.solicitud.movimientos_especiales.order_by("iniciada_en"))
        self.assertEqual(len(tramos), 2)
        self.assertEqual((tramos[0].repartidor_id, tramos[0].estado, tramos[0].motivo_cierre), (self.anterior.pk, "FINALIZADO", "SUSPENSION"))
        self.assertIsNone(tramos[0].latitud_fin)
        self.assertIsNone(tramos[0].longitud_fin)
        self.assertEqual((tramos[1].repartidor_id, tramos[1].estado), (self.nuevo.pk, "ACTIVO"))

    def test_rollback_de_revocacion_no_retira_servicios(self):
        self._asignar(EstadoSolicitud.EN_TRANSITO)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with transaction.atomic():
                revocar_rol_usuario(self.administrador, self.anterior.usuario, self._rol_actual().pk)
                transaction.set_rollback(True)
        self.assertEqual(callbacks, [])
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.repartidor_asignado_id, self.anterior.pk)
        self.assertTrue(self._rol_actual().activo)

    def test_rol_restaurado_antes_del_callback_no_retira_servicios(self):
        self._asignar(EstadoSolicitud.EN_TRANSITO)
        with self.captureOnCommitCallbacks(execute=True):
            revocar_rol_usuario(self.administrador, self.anterior.usuario, self._rol_actual().pk)
            RolUsuario.objetos.create(
                usuario=self.anterior.usuario, rol=self.rol_repartidor,
                tipo_alcance="EMPRESA", empresa=self.empresa,
            )
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.repartidor_asignado_id, self.anterior.pk)
        self.assertFalse(self.solicitud.reasignacion_pendiente)

    def test_revocar_otro_alcance_no_retira_un_rol_operativo_aun_valido(self):
        self._asignar(EstadoSolicitud.EN_TRANSITO)
        otra = Empresa.objects.create(nombre="Otra empresa", pais=self.pais)
        otro_alcance = RolUsuario.objetos.create(
            usuario=self.anterior.usuario, rol=self.rol_repartidor,
            tipo_alcance="EMPRESA", empresa=otra,
        )
        with self.captureOnCommitCallbacks(execute=True):
            revocar_rol_usuario(self.administrador, self.anterior.usuario, otro_alcance.pk)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.repartidor_asignado_id, self.anterior.pk)
        self.assertFalse(self.solicitud.reasignacion_pendiente)

    def test_tarea_recupera_perdida_de_rol_si_falla_callback(self):
        self._asignar(EstadoSolicitud.EN_TRANSITO)
        with patch("apps.solicitudes.contingencias.procesar_suspension", side_effect=RuntimeError("Fallo simulado")):
            with self.assertLogs("vitago.api", level="ERROR"):
                self._revocar()
        self.assertEqual(self.solicitud.repartidor_asignado_id, self.anterior.pk)
        with self.captureOnCommitCallbacks(execute=True):
            resultado = procesar_cierre_diario()
        self.assertEqual(resultado["servicios_retirados"], 1)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.repartidor_asignado_id, self.nuevo.pk)

    def test_tarea_detecta_catalogo_de_rol_inactivo_sin_callback(self):
        self._asignar(EstadoSolicitud.EN_TRANSITO)
        Rol.objetos.filter(pk=self.rol_repartidor.pk).update(activo=False)
        with self.captureOnCommitCallbacks(execute=True):
            resultado = procesar_cierre_diario()
        self.assertEqual(resultado["servicios_retirados"], 1)
        self.solicitud.refresh_from_db()
        self.assertIsNone(self.solicitud.repartidor_asignado_id)
        self.assertTrue(self.solicitud.reasignacion_pendiente)
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.EN_TRANSITO)

    def test_sin_rol_no_aparece_disponible_ni_tiene_bandera_positiva(self):
        RolUsuario.objetos.filter(pk=self._rol_actual().pk).update(activo=False, revocado_en=timezone.now())
        with self.assertNumQueries(1):
            perfiles = list(listar_repartidores_autorizados(self.administrador))
        por_id = {p.pk: p for p in perfiles}
        with self.assertNumQueries(0):
            self.assertFalse(puede_recibir_solicitudes(por_id[self.anterior.pk]))
            self.assertTrue(puede_recibir_solicitudes(por_id[self.nuevo.pk]))
        self.assertFalse(puede_recibir_solicitudes(self.anterior))
        self.assertNotIn(self.anterior.pk, listar_repartidores_disponibles(self.administrador).values_list("pk", flat=True))
        with self.assertRaises(ValidationError) as rechazo:
            asignar_solicitud_manualmente(self.administrador, self.solicitud.pk, {"repartidor_id": self.anterior.pk})
        self.assertIn("repartidor_id", rechazo.exception.detail)

    def test_endpoint_disponibles_excluye_rol_revocado_y_detalle_publica_false(self):
        RolUsuario.objetos.filter(pk=self._rol_actual().pk).update(activo=False, revocado_en=timezone.now())
        cliente = APIClient()
        cliente.force_authenticate(user=self.administrador)
        respuesta = cliente.get(reverse("repartidores:disponibles"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual({p["id"] for p in respuesta.data["resultados"]}, {str(self.nuevo.pk)})
        detalle = cliente.get(reverse("repartidores:detalle", kwargs={"repartidor_id": self.anterior.pk}))
        self.assertEqual(detalle.status_code, 200)
        self.assertIs(detalle.data["puede_recibir_solicitudes"], False)

    def test_rol_de_otra_empresa_y_usuario_en_otro_alcance_no_se_ofrecen(self):
        otra = Empresa.objects.create(nombre="Otra empresa", pais=self.pais)
        RolUsuario.objetos.filter(pk=self._rol_actual().pk).update(empresa=otra)
        self.assertFalse(puede_recibir_solicitudes(self.anterior))
        self.assertNotIn(self.anterior.pk, listar_repartidores_disponibles(self.administrador).values_list("pk", flat=True))
        RolUsuario.objetos.filter(usuario=self.anterior.usuario).update(empresa=self.empresa)
        Usuario.objetos.filter(pk=self.anterior.usuario_id).update(empresa=otra)
        self.assertFalse(puede_recibir_solicitudes(self.anterior))
        self.assertNotIn(self.anterior.pk, listar_repartidores_disponibles(self.administrador).values_list("pk", flat=True))

    def test_rol_inactivo_y_rol_red_no_habilitan_corporate(self):
        Rol.objetos.filter(pk=self.rol_repartidor.pk).update(activo=False)
        RolUsuario.objetos.create(usuario=self.anterior.usuario, rol=Rol.objetos.get(codigo="REPARTIDOR_RED"), tipo_alcance="GLOBAL")
        self.assertFalse(puede_recibir_solicitudes(self.anterior))
        self.assertFalse(listar_repartidores_disponibles(self.administrador).exists())

    def test_rol_corporativo_global_no_reemplaza_el_alcance_de_empresa(self):
        RolUsuario.objetos.filter(pk=self._rol_actual().pk).update(activo=False, revocado_en=timezone.now())
        Rol.objetos.filter(pk=self.rol_repartidor.pk).update(permite_alcance_global=True)
        self.rol_repartidor.refresh_from_db()
        RolUsuario.objetos.create(usuario=self.anterior.usuario, rol=self.rol_repartidor, tipo_alcance="GLOBAL")
        self.assertFalse(puede_recibir_solicitudes(self.anterior))
        self.assertNotIn(self.anterior.pk, listar_repartidores_disponibles(self.administrador).values_list("pk", flat=True))

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_puede_crear_perfil_nuevo_con_rol_valido_sin_perfil_previo(self):
        usuario = Usuario.objetos.create(correo="nuevo.red@prueba.test", nombres="Nuevo", apellidos="Red")
        RolUsuario.objetos.create(usuario=usuario, rol=Rol.objetos.get(codigo="REPARTIDOR_RED"), tipo_alcance="GLOBAL")
        vehiculo = Vehiculo.objects.create(placa="RED-NUEVO", tipo="MOTOCICLETA")
        perfil = crear_repartidor(self.administrador, {"usuario_id": usuario.pk, "vehiculo_id": vehiculo.pk})
        self.assertIsNone(perfil.empresa_id)
        perfil.estado_operativo = "AVAILABLE"
        perfil.save()
        self.assertTrue(puede_recibir_solicitudes(perfil))

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_exige_rol_global_y_no_ejecuta_contingencia_corporativa(self):
        # Datos exclusivamente sintéticos: trasladar perfiles de la fixture al
        # contexto de red no cambia configuración ni bases de desarrollo.
        Usuario.objetos.filter(pk__in=[p.usuario_id for p in self.repartidores]).update(empresa=None)
        Vehiculo.objects.filter(pk__in=[p.vehiculo_id for p in self.repartidores]).update(empresa=None)
        Repartidor.objects.filter(pk__in=[p.pk for p in self.repartidores]).update(empresa=None)
        self.anterior.refresh_from_db()
        self.nuevo.refresh_from_db()
        rol_red = Rol.objetos.get(codigo="REPARTIDOR_RED")
        asignacion = RolUsuario.objetos.create(usuario=self.anterior.usuario, rol=rol_red, tipo_alcance="GLOBAL")
        self.assertTrue(puede_recibir_solicitudes(self.anterior))
        self.assertFalse(puede_recibir_solicitudes(self.nuevo))
        self.assertEqual(set(listar_repartidores_disponibles(self.administrador).values_list("pk", flat=True)), {self.anterior.pk})
        asignar_solicitud_manualmente(self.administrador, self.solicitud.pk, {"repartidor_id": self.anterior.pk})
        with patch("apps.solicitudes.contingencias.programar_suspension") as programar:
            with self.captureOnCommitCallbacks(execute=True):
                revocar_rol_usuario(self.administrador, self.anterior.usuario, asignacion.pk)
        programar.assert_not_called()
        self.assertEqual(procesar_suspension(self.anterior.usuario_id), 0)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.repartidor_asignado_id, self.anterior.pk)
        self.assertFalse(puede_recibir_solicitudes(self.anterior))
        self.assertFalse(listar_repartidores_disponibles(self.administrador).exists())
