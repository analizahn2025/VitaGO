"""Cupo reservado por solicitud, asignación y configuración administrativa."""

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from apps.repartidores.models import Repartidor
from apps.organizaciones.models import HistorialLimitesMotoristas
from apps.organizaciones.limites import configurar_limites_empresa
from apps.repartidores.selectores import listar_repartidores_disponibles
from apps.repartidores.serializadores import SerializadorRepartidor
from apps.solicitudes.carga import actualizar_cantidad_tubos
from apps.solicitudes.excepciones import CupoTubosInsuficiente, LimiteSolicitudesRepartidor
from apps.solicitudes.models import Solicitud
from apps.solicitudes.servicios import asignar_solicitud_manualmente, cambiar_estado_solicitud, crear_solicitud
from apps.solicitudes.tests import test_asignaciones as datos


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasCupoTubos(TestCase):
    setUpTestData = classmethod(datos.PruebasAsignacionesSolicitud.setUpTestData.__func__)
    setUp = datos.PruebasAsignacionesSolicitud.setUp
    _registrar_gps = datos.PruebasAsignacionesSolicitud._registrar_gps
    _datos_creacion_automatica = datos.PruebasAsignacionesSolicitud._datos_creacion_automatica

    def _nueva(self, tubos, repartidor=None, estado="PENDING"):
        return Solicitud.objects.create(
            cantidad_tubos=tubos, numero=f"TUBOS-{Solicitud.objects.count()}", empresa=self.empresa,
            solicitada_por=self.administrador, prioridad="NORMAL", origen=self.origen, destino=self.destino,
            repartidor_asignado=repartidor, estado=estado,
        )

    def _asignar(self, tubos, repartidor=None):
        solicitud = self._nueva(tubos)
        return asignar_solicitud_manualmente(self.administrador, solicitud.pk, {"repartidor_id": (repartidor or self.repartidores[0]).pk})

    def _perfil(self, repartidor=None):
        r = Repartidor.objects.select_related("usuario", "empresa", "vehiculo").get(pk=(repartidor or self.repartidores[0]).pk)
        return SerializadorRepartidor(r).data

    def test_dieciocho_mas_dos_llena_veinte_sin_llegar_a_cinco_solicitudes(self):
        self._asignar(18)
        antes = self._perfil()
        self.assertEqual((antes["capacidad"], antes["tubos_disponibles"]), ("AVAILABLE_SPACE", 2))
        self._asignar(2)
        despues = self._perfil()
        self.assertEqual((despues["solicitudes_activas"], despues["tubos_comprometidos"]), (2, 20))
        self.assertEqual(despues["capacidad"], "FULL")
        self.assertFalse(despues["puede_recibir_solicitudes"])
        self.assertEqual(despues["tubos_reservados"], 20)
        self.assertEqual(despues["tubos_en_transporte"], 0)

    def test_dieciocho_mas_tres_rechaza_409_y_preserva_carga(self):
        self._asignar(18)
        with self.assertRaises(CupoTubosInsuficiente) as error:
            self._asignar(3)
        self.assertEqual(error.exception.status_code, 409)
        self.assertIn("repartidor_id", error.exception.detail)
        self.assertEqual(self._perfil()["tubos_comprometidos"], 18)

    def test_automatico_salta_motorista_cercano_sin_cupo(self):
        self._asignar(18)
        self._registrar_gps(self.repartidores[0], "14.072300", "-87.192100")
        self._registrar_gps(self.repartidores[1], "14.082300", "-87.182100")
        datos_creacion = {**self._datos_creacion_automatica(), "cantidad_tubos": 3}
        solicitud = crear_solicitud(self.administrador, datos_creacion)
        self.assertEqual(solicitud.repartidor_asignado_id, self.repartidores[1].pk)

    def test_disponibles_filtra_por_tamano_del_pedido(self):
        self._asignar(18)
        r = self.repartidores[0]
        self.assertTrue(listar_repartidores_disponibles(self.administrador, {"cantidad_tubos": 2}).filter(pk=r.pk).exists())
        self.assertFalse(listar_repartidores_disponibles(self.administrador, {"cantidad_tubos": 3}).filter(pk=r.pk).exists())

    def test_sumas_repetidas_no_se_deduplican(self):
        self._asignar(5)
        self._asignar(5)
        self.assertEqual(self._perfil()["tubos_comprometidos"], 10)

    def test_cinco_solicitudes_siguen_bloqueando_aunque_sobren_tubos(self):
        for _ in range(5):
            self._asignar(1)
        with self.assertRaises(LimiteSolicitudesRepartidor):
            self._asignar(1)

    def test_pendientes_y_terminales_no_reservan_tubos(self):
        for estado in ("PENDING", "DELIVERED", "CANCELLED", "PICKUP_FAILED", "DELIVERY_FAILED"):
            self._nueva(20, self.repartidores[0], estado)
        self.assertEqual(self._perfil()["tubos_comprometidos"], 0)

    def test_recogidos_se_separan_de_reservados_sin_duplicar_total(self):
        self._nueva(8, self.repartidores[0], "PICKED_UP")
        self._nueva(10, self.repartidores[0], "ASSIGNED")
        perfil = self._perfil()
        self.assertEqual((perfil["tubos_comprometidos"], perfil["tubos_en_transporte"], perfil["tubos_reservados"]), (18, 8, 10))

    def test_cancelar_libera_tubos_y_mantiene_historial(self):
        solicitud = self._asignar(20)
        cambiar_estado_solicitud(self.administrador, solicitud.pk, {"estado_destino": "CANCELLED", "motivo": "Prueba"})
        self.assertEqual(self._perfil()["tubos_comprometidos"], 0)
        self.assertTrue(Solicitud.objects.filter(pk=solicitud.pk, cantidad_tubos=20).exists())

    def test_reasignar_transfiere_reserva(self):
        solicitud = self._asignar(18)
        asignar_solicitud_manualmente(self.administrador, solicitud.pk, {"repartidor_id": self.repartidores[1].pk})
        self.assertEqual(self._perfil()["tubos_comprometidos"], 0)
        self.assertEqual(self._perfil(self.repartidores[1])["tubos_comprometidos"], 18)

    def test_limite_es_por_empresa_y_queda_auditado(self):
        r = self.repartidores[0]
        configurar_limites_empresa(self.administrador, self.empresa.pk, {"limite_tubos": 30})
        self.assertEqual(self._perfil()["limite_tubos"], 30)
        self.assertEqual(self._perfil(self.repartidores[1])["limite_tubos"], 30)
        self.assertEqual(HistorialLimitesMotoristas.objects.get(empresa=self.empresa).limites_nuevos["limite_tubos"], 30)

    def test_no_reduce_limite_por_debajo_de_reserva(self):
        self._asignar(18)
        with self.assertRaises(ValidationError) as error:
            configurar_limites_empresa(self.administrador, self.empresa.pk, {"limite_tubos": 17})
        self.assertIn("limite_tubos", error.exception.detail)

    def test_motorista_no_configura_su_propio_limite(self):
        r = self.repartidores[0]
        with self.assertRaises(PermissionDenied):
            configurar_limites_empresa(r.usuario, self.empresa.pk, {"limite_tubos": 99})

    def test_historica_desconocida_bloquea_nuevas_hasta_regularizacion(self):
        solicitud = self._nueva(None, self.repartidores[0], "PICKED_UP")
        self.assertFalse(self._perfil()["puede_recibir_solicitudes"])
        self.assertEqual(self._perfil()["solicitudes_sin_cantidad_tubos"], 1)
        actualizar_cantidad_tubos(self.administrador, solicitud.pk, {"cantidad_tubos": 18, "motivo": "Conteo confirmado"})
        self.assertEqual(self._perfil()["tubos_disponibles"], 2)

    def test_correccion_conocida_no_aumenta_cupo_ni_modifica_recogidos(self):
        solicitud = self._asignar(18)
        with self.assertRaises(ValidationError):
            actualizar_cantidad_tubos(self.administrador, solicitud.pk, {"cantidad_tubos": 21, "motivo": "Prueba"})
        Solicitud.objects.filter(pk=solicitud.pk).update(estado="PICKED_UP")
        with self.assertRaises(ValidationError):
            actualizar_cantidad_tubos(self.administrador, solicitud.pk, {"cantidad_tubos": 1, "motivo": "Prueba"})

    def test_api_rechaza_cantidad_invalida_y_devuelve_campos_de_carga(self):
        cliente = APIClient(); cliente.force_authenticate(self.administrador)
        respuesta = cliente.patch(reverse("repartidores:detalle", args=[self.repartidores[0].pk]), {"limite_tubos": 25}, format="json")
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("limite_tubos", respuesta.data)
        respuesta = cliente.patch(reverse("organizaciones:limites-motoristas-empresa", args=[self.empresa.pk]), {"limite_tubos": 25}, format="json")
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertEqual(respuesta.data["limite_tubos"], 25)
        for valor in (0, -1, "abc", 1.5):
            respuesta = cliente.patch(reverse("solicitudes:cantidad-tubos", args=[self.solicitud.pk]), {"cantidad_tubos": valor, "motivo": "Prueba"}, format="json")
            self.assertEqual(respuesta.status_code, 400)
            self.assertIn("cantidad_tubos", respuesta.data)

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_global_comparte_cupo_entre_clientes(self):
        from apps.usuarios.models import Rol, RolUsuario, Usuario
        from apps.flota.models import Vehiculo
        from apps.organizaciones.models import Empresa
        r = self.repartidores[0]
        Repartidor.objects.filter(pk=r.pk).update(empresa=None)
        Usuario.objetos.filter(pk=r.usuario_id).update(empresa=None)
        Vehiculo.objects.filter(pk=r.vehiculo_id).update(empresa=None)
        RolUsuario.objetos.filter(usuario_id=r.usuario_id).update(activo=False, revocado_en=timezone.now())
        RolUsuario.objetos.create(usuario_id=r.usuario_id, rol=Rol.objetos.get(codigo="REPARTIDOR_RED"), tipo_alcance="GLOBAL", asignado_por=self.administrador)
        self._asignar(18)
        otro_cliente = Empresa.objects.create(nombre="Otro cliente", pais=self.empresa.pais)
        solicitud = self._nueva(3)
        Solicitud.objects.filter(pk=solicitud.pk).update(empresa=otro_cliente)
        with self.assertRaises(CupoTubosInsuficiente):
            asignar_solicitud_manualmente(self.administrador, solicitud.pk, {"repartidor_id": r.pk})
