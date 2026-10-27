"""Intercalación por distancia, precedencias y estabilidad de cada parada."""

from django.test import TestCase, override_settings

from apps.rutas.models import VersionRuta
from apps.rutas.selectores import obtener_paradas_operativas
from apps.rutas.tests import test_ordenamiento as datos
from apps.seguimiento.models import RegistroUbicacion
from apps.solicitudes.models import Solicitud
from apps.solicitudes.opciones import EstadoSolicitud


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasParadasCercanas(TestCase):
    setUpTestData = classmethod(datos.PruebasOrdenamientoCercania.setUpTestData.__func__)
    setUp = datos.PruebasOrdenamientoCercania.setUp
    motorista = datos.PruebasOrdenamientoCercania.motorista
    _crear_solicitud = datos.PruebasOrdenamientoCercania._crear_solicitud
    _cliente = datos.PruebasOrdenamientoCercania._cliente
    _gps = datos.PruebasOrdenamientoCercania._gps
    _ubicacion = datos.PruebasOrdenamientoCercania._ubicacion
    _servicio = datos.PruebasOrdenamientoCercania._servicio
    _sincronizar = datos.PruebasOrdenamientoCercania._sincronizar
    _leer = datos.PruebasOrdenamientoCercania._leer

    def _paradas(self):
        return [(p["solicitud_id"], p["tipo"]) for p in obtener_paradas_operativas(self.motorista)]

    def test_dos_servicios_recoge_ambos_y_entrega_el_cercano_primero(self):
        a = self._servicio("PAR-A", ".001", ".100", minutos_atras=20)
        b = self._servicio("PAR-B", ".002", ".003", minutos_atras=1)
        self._sincronizar()
        self.assertEqual(self._paradas(), [(a.pk, "RECOLECCION"), (b.pk, "RECOLECCION"),
                                           (b.pk, "ENTREGA"), (a.pk, "ENTREGA")])
        # La lectura conserva la intercalación, en vez de reagrupar por solicitud.
        datos_http = self._leer()
        self.assertEqual([p["solicitud_id"] for p in datos_http["paradas"]],
                         [str(a.pk), str(b.pk), str(b.pk), str(a.pk)])
        self.assertEqual(datos_http["flujo_actual"]["tramo_id"], f"{a.pk}:RECOLECCION")

    def test_entregas_ya_recogidas_se_ordenan_por_destino(self):
        a = self._servicio("PAR-A", ".001", ".100", estado=EstadoSolicitud.RECOLECTADA, minutos_atras=20)
        b = self._servicio("PAR-B", ".002", ".003", estado=EstadoSolicitud.RECOLECTADA, minutos_atras=1)
        self._sincronizar()
        self.assertEqual(self._paradas(), [(b.pk, "ENTREGA"), (a.pk, "ENTREGA")])

    def test_entrega_cercana_puede_preceder_recoleccion_lejana(self):
        a = self._servicio("PAR-A", ".100", ".101", minutos_atras=20)
        b = self._servicio("PAR-B", ".010", ".001", estado=EstadoSolicitud.RECOLECTADA, minutos_atras=1)
        self._sincronizar()
        self.assertEqual(self._paradas()[0], (b.pk, "ENTREGA"))
        self.assertEqual(self._paradas()[1:], [(a.pk, "RECOLECCION"), (a.pk, "ENTREGA")])

    def test_destino_cercano_no_habilita_entregar_un_paquete_sin_recoger(self):
        a = self._servicio("PAR-A", ".100", ".0001", minutos_atras=20)
        b = self._servicio("PAR-B", ".001", ".002", minutos_atras=1)
        self._sincronizar()
        self.assertEqual(self._paradas()[0], (b.pk, "RECOLECCION"))
        self.assertLess(self._paradas().index((a.pk, "RECOLECCION")), self._paradas().index((a.pk, "ENTREGA")))

    def test_cinco_solicitudes_generan_diez_paradas_con_precedencias_validas(self):
        servicios = [self._servicio(f"PAR-{i}", f".00{i}", f".10{i}") for i in range(1, 6)]
        self._sincronizar()
        paradas = self._paradas()
        self.assertEqual(len(paradas), len(set(paradas)))
        self.assertEqual(len(paradas), 10)
        self.assertEqual([tipo for _, tipo in paradas[:5]], ["RECOLECCION"] * 5)
        for s in servicios:
            self.assertLess(paradas.index((s.pk, "RECOLECCION")), paradas.index((s.pk, "ENTREGA")))

    def test_nueva_asignacion_preserva_entrega_en_curso_pero_no_agrupa_el_resto(self):
        a = self._servicio("PAR-A", ".001", ".100", estado=EstadoSolicitud.EN_TRANSITO)
        self._sincronizar()
        b = self._servicio("PAR-B", ".101", ".200", minutos_atras=1)
        c = self._servicio("PAR-C", ".102", ".103", minutos_atras=0)
        self._sincronizar()
        self.assertEqual(self._paradas(), [(a.pk, "ENTREGA"), (b.pk, "RECOLECCION"),
                                           (c.pk, "RECOLECCION"), (c.pk, "ENTREGA"), (b.pk, "ENTREGA")])

    def test_foto_pendiente_no_pierde_su_parada_por_una_nueva_asignacion(self):
        for estado, tipo in ((EstadoSolicitud.EN_RECOLECCION, "RECOLECCION"),
                             (EstadoSolicitud.EN_DESTINO, "ENTREGA")):
            with self.subTest(estado=estado):
                Solicitud.objects.all().update(estado=EstadoSolicitud.CANCELADA)
                a = self._servicio(f"PAR-{estado}", ".100", ".101", estado=estado)
                self._sincronizar()
                self._servicio(f"NUEVA-{estado}", ".001", ".002", minutos_atras=0)
                self._sincronizar()
                self.assertEqual(self._paradas()[0], (a.pk, tipo))

    def test_sin_gps_conserva_pares_intercalados_completos(self):
        a = self._servicio("PAR-A", ".001", ".100", minutos_atras=20)
        b = self._servicio("PAR-B", ".002", ".003", minutos_atras=1)
        ruta = self._sincronizar()
        anterior = self._paradas()
        self.assertEqual(anterior[1], (b.pk, "RECOLECCION"))
        RegistroUbicacion.objects.filter(pk=self.gps.pk).update(precision_metros=None)
        self._sincronizar(VersionRuta.Motivo.CAMBIO_ESTADO)
        self.assertEqual(self._paradas(), anterior)
        self.assertEqual(ruta.versiones.count(), 1)
        self.assertEqual(anterior[-1], (a.pk, "ENTREGA"))

    def test_prioritario_pendiente_impone_entrega_directa_tras_su_recoleccion(self):
        a = self._servicio("PAR-PRIORIDAD", ".001", ".100", prioridad="PRIORITY")
        b = self._servicio("PAR-NORMAL", ".002", ".003", minutos_atras=0)
        self._sincronizar()
        self.assertEqual(self._paradas(), [(a.pk, "RECOLECCION"), (a.pk, "ENTREGA"),
                                           (b.pk, "RECOLECCION"), (b.pk, "ENTREGA")])

    def test_especial_pendiente_permanece_junto_a_su_recoleccion(self):
        a = self._servicio("PAR-ESPECIAL", ".001", None, modalidad="ESPECIAL")
        b = self._servicio("PAR-NORMAL", ".002", ".003", minutos_atras=0)
        self._sincronizar()
        self.assertEqual(self._paradas(), [(a.pk, "RECOLECCION"), (a.pk, "ENVIO_ESPECIAL"),
                                           (b.pk, "RECOLECCION"), (b.pk, "ENTREGA")])

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_tambien_intercala_paradas(self):
        self.test_dos_servicios_recoge_ambos_y_entrega_el_cercano_primero()
