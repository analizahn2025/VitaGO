"""Tubos/frascos independientes, artículos históricos y administración de cupos."""

from django.test import TestCase, TransactionTestCase, override_settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from apps.organizaciones.limites import configurar_limites_empresa, configurar_limites_red
from apps.organizaciones.models import Empresa, HistorialLimitesMotoristas
from apps.organizaciones.tests import test_limites_motoristas as datos_limites
from apps.repartidores.models import Repartidor
from apps.repartidores.selectores import listar_repartidores_disponibles
from apps.repartidores.serializadores import SerializadorRepartidor
from apps.repartidores.resumenes import construir_resumenes
from apps.rutas.selectores import obtener_paradas_operativas
from apps.solicitudes.carga import actualizar_carga_recipientes
from apps.solicitudes.excepciones import CupoRecipientesInsuficiente, LimiteSolicitudesRepartidor
from apps.solicitudes.models import ArticuloSolicitud, EventoSolicitud, Solicitud
from apps.solicitudes.recipientes import validar_cantidades_recipientes
from apps.solicitudes.serializadores import SerializadorCreacionSolicitud, SerializadorSolicitudDetalle
from apps.solicitudes.servicios import asignar_solicitud_manualmente, cambiar_estado_solicitud, crear_solicitud
from apps.solicitudes.tests import test_asignaciones as datos


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasTubosFrascos(TestCase):
    setUpTestData = classmethod(datos.PruebasAsignacionesSolicitud.setUpTestData.__func__)
    setUp = datos.PruebasAsignacionesSolicitud.setUp
    _registrar_gps = datos.PruebasAsignacionesSolicitud._registrar_gps
    _datos_creacion_automatica = datos.PruebasAsignacionesSolicitud._datos_creacion_automatica
    _preparar_red = datos_limites.PruebasLimitesCompartidos._preparar_red

    def _nueva(self, tubos=0, frascos=1, *, estado="PENDING", repartidor=None):
        return Solicitud.objects.create(numero=f"FRASCOS-{Solicitud.objects.count()}", empresa=self.empresa,
            solicitada_por=self.administrador, origen=self.origen, destino=self.destino,
            cantidad_tubos=tubos, cantidad_frascos=frascos, prioridad="NORMAL", estado=estado,
            repartidor_asignado=repartidor)

    def _asignar(self, tubos=0, frascos=1, repartidor=None):
        solicitud = self._nueva(tubos, frascos)
        return asignar_solicitud_manualmente(self.administrador, solicitud.pk, {"repartidor_id": (repartidor or self.repartidores[0]).pk})

    def _perfil(self, repartidor=None):
        r = Repartidor.objects.select_related("usuario", "empresa", "vehiculo").get(pk=(repartidor or self.repartidores[0]).pk)
        return SerializadorRepartidor(r).data

    def _cliente(self, usuario=None):
        cliente = APIClient(); cliente.force_authenticate(usuario or self.administrador)
        return cliente

    def test_crear_solo_frascos_sin_articulos_asigna_automaticamente(self):
        solicitud = crear_solicitud(self.administrador, {**self._datos_creacion_automatica(), "cantidad_tubos": 0, "cantidad_frascos": 3})
        self.assertIsNotNone(solicitud.repartidor_asignado_id)
        self.assertEqual((solicitud.cantidad_tubos, solicitud.cantidad_frascos), (0, 3))
        self.assertFalse(ArticuloSolicitud.objects.exists())

    def test_crear_carga_mixta_conserva_ambas_cantidades(self):
        solicitud = crear_solicitud(self.administrador, {**self._datos_creacion_automatica(), "cantidad_tubos": 4, "cantidad_frascos": 2})
        self.assertEqual((solicitud.cantidad_tubos, solicitud.cantidad_frascos), (4, 2))

    def test_carga_vacia_no_se_admite(self):
        with self.assertRaises(ValidationError) as error:
            validar_cantidades_recipientes(0, 0)
        self.assertEqual(set(error.exception.detail), {"cantidad_tubos", "cantidad_frascos"})

    def test_invalidos_tienen_nombre_de_campo_estable(self):
        for valor in (-1, 1.2, True, None, "2", 2147483648):
            with self.subTest(valor=valor), self.assertRaises(ValidationError) as error:
                validar_cantidades_recipientes(1, valor)
            self.assertIn("cantidad_frascos", error.exception.detail)

    def test_dto_no_contiene_articulos_y_conserva_historia_aparte(self):
        articulo = ArticuloSolicitud.objects.create(solicitud=self.solicitud, tipo_articulo="Registro antiguo", cantidad=2)
        datos_salida = SerializadorSolicitudDetalle(self.solicitud).data
        self.assertNotIn("articulos", datos_salida)
        self.assertEqual(datos_salida["articulos_historicos"][0]["id"], str(articulo.pk))
        self.assertTrue(ArticuloSolicitud.objects.filter(pk=articulo.pk).exists())

    def test_servidor_rechaza_articulos_en_servicio_directo(self):
        with self.assertRaises(ValidationError) as error:
            crear_solicitud(self.administrador, {**self._datos_creacion_automatica(), "articulos": [{"tipo_articulo": "Obsoleto"}]})
        self.assertIn("articulos", error.exception.detail)

    def test_serializador_permite_solo_frascos_y_omite_tubos_como_cero(self):
        datos_entrada = self._datos_creacion_automatica()
        datos_entrada.pop("cantidad_tubos", None)
        serializador = SerializadorCreacionSolicitud(data={**datos_entrada, "cantidad_frascos": 1})
        self.assertTrue(serializador.is_valid(), serializador.errors)
        self.assertEqual(serializador.validated_data["cantidad_tubos"], 0)

    def test_frascos_dieciocho_mas_tres_rechaza_409(self):
        self._asignar(frascos=18)
        with self.assertRaises(CupoRecipientesInsuficiente) as error:
            self._asignar(frascos=3)
        self.assertEqual(error.exception.status_code, 409)
        self.assertIn("repartidor_id", error.exception.detail)
        self.assertEqual(self._perfil()["frascos_comprometidos"], 18)

    def test_lleno_en_ambos_cupos_no_recibe_mas(self):
        self._asignar(tubos=20, frascos=0)
        self._asignar(tubos=0, frascos=20)
        perfil = self._perfil()
        self.assertEqual(perfil["capacidad"], "FULL")
        self.assertFalse(perfil["puede_recibir_solicitudes"])

    def test_agotar_frascos_permite_tubos_pero_no_otro_frasco(self):
        self._asignar(frascos=20)
        r = self.repartidores[0]
        self.assertEqual(self._perfil()["capacidad"], "AVAILABLE_SPACE")
        self.assertTrue(listar_repartidores_disponibles(self.administrador, {"cantidad_tubos": 1}).filter(pk=r.pk).exists())
        self.assertFalse(listar_repartidores_disponibles(self.administrador, {"cantidad_frascos": 1}).filter(pk=r.pk).exists())

    def test_carga_antigua_excedida_no_admite_ninguno_de_los_tipos(self):
        self._nueva(tubos=21, frascos=0, estado="ASSIGNED", repartidor=self.repartidores[0])
        perfil = self._perfil()
        self.assertEqual(perfil["capacidad"], "FULL")
        self.assertFalse(perfil["puede_recibir_solicitudes"])
        self.assertFalse(listar_repartidores_disponibles(self.administrador, {"cantidad_frascos": 1}).filter(pk=self.repartidores[0].pk).exists())

    def test_pedido_mixto_debe_caber_en_los_dos_cupos(self):
        self._asignar(tubos=18, frascos=18)
        r = self.repartidores[0]
        for tubos, frascos, esperado in ((2, 2, True), (3, 2, False), (2, 3, False)):
            with self.subTest(tubos=tubos, frascos=frascos):
                self.assertEqual(listar_repartidores_disponibles(self.administrador, {"cantidad_tubos": tubos, "cantidad_frascos": frascos}).filter(pk=r.pk).exists(), esperado)

    def test_automatico_salta_el_mas_cercano_si_no_caben_frascos(self):
        self._asignar(frascos=18)
        solicitud = crear_solicitud(self.administrador, {**self._datos_creacion_automatica(), "cantidad_tubos": 0, "cantidad_frascos": 3})
        self.assertEqual(solicitud.repartidor_asignado_id, self.repartidores[1].pk)

    def test_cinco_solicitudes_siguen_siendo_el_maximo(self):
        for _ in range(5):
            self._asignar(frascos=1)
        with self.assertRaises(LimiteSolicitudesRepartidor):
            self._asignar(frascos=1)

    def test_cancelar_libera_ambos_cupos_sin_borrar_solicitud(self):
        solicitud = self._asignar(tubos=8, frascos=9)
        cambiar_estado_solicitud(self.administrador, solicitud.pk, {"estado_destino": "CANCELLED", "motivo": "Prueba"})
        perfil = self._perfil()
        self.assertEqual((perfil["tubos_comprometidos"], perfil["frascos_comprometidos"]), (0, 0))
        self.assertTrue(Solicitud.objects.filter(pk=solicitud.pk, cantidad_frascos=9).exists())

    def test_reasignar_transfiere_ambas_reservas(self):
        solicitud = self._asignar(tubos=8, frascos=9)
        asignar_solicitud_manualmente(self.administrador, solicitud.pk, {"repartidor_id": self.repartidores[1].pk})
        self.assertEqual(self._perfil()["frascos_comprometidos"], 0)
        nuevo = self._perfil(self.repartidores[1])
        self.assertEqual((nuevo["tubos_comprometidos"], nuevo["frascos_comprometidos"]), (8, 9))

    def test_reservados_y_transportados_no_se_suman_doble(self):
        self._nueva(frascos=4, estado="PICKED_UP", repartidor=self.repartidores[0])
        self._nueva(frascos=5, estado="ASSIGNED", repartidor=self.repartidores[0])
        perfil = self._perfil()
        self.assertEqual((perfil["frascos_comprometidos"], perfil["frascos_en_transporte"], perfil["frascos_reservados"]), (9, 4, 5))

    def test_pendientes_y_terminales_no_reservan_frascos(self):
        for estado in ("PENDING", "DELIVERED", "CANCELLED", "PICKUP_FAILED", "DELIVERY_FAILED"):
            self._nueva(frascos=20, estado=estado, repartidor=self.repartidores[0])
        self.assertEqual(self._perfil()["frascos_comprometidos"], 0)

    def test_limite_configurado_se_aplica_a_cada_motorista_y_se_audita(self):
        configurar_limites_empresa(self.administrador, self.empresa.pk, {"limite_frascos": 7})
        for r in self.repartidores:
            self._asignar(frascos=7, repartidor=r)
            self.assertEqual(self._perfil(r)["limite_frascos"], 7)
        historial = HistorialLimitesMotoristas.objects.get()
        self.assertEqual((historial.limites_anteriores["limite_frascos"], historial.limites_nuevos["limite_frascos"]), (20, 7))

    def test_otras_empresas_conservan_su_limite(self):
        otra = Empresa.objects.create(nombre="Otra empresa", pais=self.pais)
        configurar_limites_empresa(self.administrador, self.empresa.pk, {"limite_frascos": 7})
        otra.refresh_from_db()
        self.assertEqual(otra.limite_frascos_por_motorista, 20)

    def test_admin_no_puede_bajar_frascos_por_debajo_de_lo_reservado(self):
        self._asignar(frascos=18)
        with self.assertRaises(ValidationError) as error:
            configurar_limites_empresa(self.administrador, self.empresa.pk, {"limite_frascos": 17})
        self.assertIn("limite_frascos", error.exception.detail)

    def test_motorista_no_configura_frascos(self):
        with self.assertRaises(PermissionDenied):
            configurar_limites_empresa(self.repartidores[0].usuario, self.empresa.pk, {"limite_frascos": 30})

    def test_api_configura_frascos_por_empresa_y_no_individualmente(self):
        cliente = self._cliente()
        ruta = reverse("organizaciones:limites-motoristas-empresa", args=[self.empresa.pk])
        respuesta = cliente.patch(ruta, {"limite_frascos": 12}, format="json")
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertEqual(respuesta.data["limite_frascos"], 12)
        respuesta = cliente.patch(reverse("repartidores:detalle", args=[self.repartidores[0].pk]), {"limite_frascos": 12}, format="json")
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("limite_frascos", respuesta.data)

    def test_api_configuracion_rechaza_limites_de_frascos_invalidos(self):
        ruta = reverse("organizaciones:limites-motoristas-empresa", args=[self.empresa.pk])
        for valor in (0, -1, True, 1.5, None, 2147483648):
            with self.subTest(valor=valor):
                respuesta = self._cliente().patch(ruta, {"limite_frascos": valor}, format="json")
                self.assertEqual(respuesta.status_code, 400)
                self.assertIn("limite_frascos", respuesta.data)

    def test_motorista_no_corrige_su_propia_carga(self):
        solicitud = self._asignar(frascos=3)
        respuesta = self._cliente(self.repartidores[0].usuario).patch(reverse("solicitudes:carga", args=[solicitud.pk]), {"cantidad_frascos": 1, "motivo": "Prueba"}, format="json")
        self.assertEqual(respuesta.status_code, 403)

    def test_correccion_frascos_terminal_conserva_nombre_del_campo(self):
        solicitud = self._nueva(frascos=1, estado="DELIVERED", repartidor=self.repartidores[0])
        respuesta = self._cliente().patch(reverse("solicitudes:carga", args=[solicitud.pk]), {"cantidad_frascos": 2, "motivo": "Prueba"}, format="json")
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("cantidad_frascos", respuesta.data)

    def test_correccion_administrativa_de_frascos_es_auditada(self):
        solicitud = self._asignar(tubos=2, frascos=3)
        respuesta = self._cliente().patch(reverse("solicitudes:carga", args=[solicitud.pk]), {"cantidad_frascos": 5, "motivo": "Conteo confirmado"}, format="json")
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertEqual(respuesta.data["cantidad_frascos"], 5)
        evento = EventoSolicitud.objects.get(tipo="CARGA_ACTUALIZADA")
        self.assertEqual((evento.metadatos["cantidad_frascos_anterior"], evento.metadatos["cantidad_frascos_nueva"]), (3, 5))

    def test_correccion_no_supera_el_cupo_del_motorista(self):
        solicitud = self._asignar(frascos=18)
        with self.assertRaises(ValidationError) as error:
            actualizar_carga_recipientes(self.administrador, solicitud.pk, {"cantidad_frascos": 21, "motivo": "Prueba"})
        self.assertIn("cantidad_frascos", error.exception.detail)

    def test_no_se_cambia_cantidad_conocida_despues_de_recoger(self):
        solicitud = self._asignar(frascos=3)
        Solicitud.objects.filter(pk=solicitud.pk).update(estado="PICKED_UP")
        with self.assertRaises(ValidationError):
            actualizar_carga_recipientes(self.administrador, solicitud.pk, {"cantidad_frascos": 2, "motivo": "Prueba"})

    def test_frascos_historicos_desconocidos_se_completan_una_vez(self):
        solicitud = self._nueva(tubos=3, frascos=None, estado="PICKED_UP", repartidor=self.repartidores[0])
        self.assertFalse(self._perfil()["puede_recibir_solicitudes"])
        actualizar_carga_recipientes(self.administrador, solicitud.pk, {"cantidad_frascos": 2, "motivo": "Conteo histórico confirmado"})
        self.assertTrue(self._perfil()["puede_recibir_solicitudes"])
        self.assertTrue(EventoSolicitud.objects.get(tipo="CARGA_ACTUALIZADA").metadatos["regularizacion_historica"])

    def test_limite_no_se_reduce_con_frascos_desconocidos(self):
        self._nueva(tubos=1, frascos=None, estado="ASSIGNED", repartidor=self.repartidores[0])
        with self.assertRaises(ValidationError):
            configurar_limites_empresa(self.administrador, self.empresa.pk, {"limite_frascos": 19})

    def test_ruta_incluye_ambos_conteos(self):
        solicitud = self._asignar(tubos=3, frascos=2)
        paradas = obtener_paradas_operativas(self.repartidores[0])
        self.assertEqual((paradas[0]["cantidad_tubos"], paradas[0]["cantidad_frascos"]), (3, 2))

    def test_resumen_diario_incluye_frascos_y_carga_actual(self):
        self._nueva(tubos=1, frascos=3, estado="DELIVERED", repartidor=self.repartidores[0])
        Solicitud.objects.filter(estado="DELIVERED").update(recolectada_en=timezone.now(), entregada_en=timezone.now())
        r = Repartidor.objects.select_related("empresa__pais", "usuario", "vehiculo").get(pk=self.repartidores[0].pk)
        resumen = construir_resumenes([r])[0]
        self.assertEqual(resumen["frascos"]["entregados_conocidos"], 3)
        self.assertIn("frascos_disponibles", resumen["carga_actual"])

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_comparte_limite_de_frascos_entre_todos_los_clientes(self):
        self._preparar_red()
        configurar_limites_red(self.administrador, {"limite_frascos": 7})
        self._asignar(frascos=5)
        otra = Empresa.objects.create(nombre="Otro cliente", pais=self.pais)
        solicitud = self._nueva(frascos=3)
        solicitud.empresa = otra; solicitud.save()
        with self.assertRaises(CupoRecipientesInsuficiente):
            asignar_solicitud_manualmente(self.administrador, solicitud.pk, {"repartidor_id": self.repartidores[0].pk})


class PruebasMigracionFrascos(TransactionTestCase):
    serialized_rollback = True

    def test_migracion_conserva_articulos_y_no_infiere_frascos_anteriores(self):
        datos.PruebasAsignacionesSolicitud.setUpTestData.__func__(type(self))
        solicitud = Solicitud.objects.create(numero="HISTORIA-MIGRACION", empresa=self.empresa,
            solicitada_por=self.administrador, origen=self.origen, destino=self.destino,
            prioridad="NORMAL", cantidad_tubos=2)
        articulo = ArticuloSolicitud.objects.create(solicitud=solicitud, tipo_articulo="Historia conservada", cantidad=1)
        executor = MigrationExecutor(connection)
        destino = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate([("organizaciones", "0003_limites_motoristas_compartidos"), ("solicitudes", "0008_carga_tubos_y_temperatura")])
        finally:
            MigrationExecutor(connection).migrate(destino)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.cantidad_tubos, 2)
        self.assertIsNone(solicitud.cantidad_frascos)
        self.assertTrue(ArticuloSolicitud.objects.filter(pk=articulo.pk).exists())
