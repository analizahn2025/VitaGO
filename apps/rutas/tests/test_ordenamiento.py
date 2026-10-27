"""Cercanía GPS estable, sin red ni modificaciones de datos de desarrollo."""

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.db import connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.jornadas.models import JornadaRepartidor
from apps.rutas.models import CalculoRutaVial, ConsumoRutasGoogle, VersionRuta
from apps.rutas.ruta_vial import firma_paradas
from apps.rutas.selectores import obtener_paradas_operativas
from apps.rutas.servicios import sincronizar_ruta
from apps.rutas.tests import test_mi_ruta as datos_ruta
from apps.seguimiento.llegadas import detectar_llegada
from apps.seguimiento.models import RegistroUbicacion
from apps.seguimiento.vigencia import posiciones_vigentes
from apps.solicitudes.models import AsignacionSolicitud, EventoSolicitud, Solicitud
from apps.solicitudes.opciones import (
    EstadoAsignacionSolicitud, EstadoSolicitud, ModalidadSolicitud,
    PrioridadSolicitud, TipoEventoSolicitud,
)
from apps.ubicaciones.models import Ubicacion


@override_settings(
    MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL",
    ANTIGUEDAD_GPS_ASIGNACION_SEGUNDOS=120, PRECISION_GPS_ASIGNACION_METROS=50,
    HABILITAR_RUTAS_GOOGLE=True, CLAVE_API_GOOGLE_MAPS="solo-pruebas",
)
class PruebasOrdenamientoCercania(TestCase):
    setUpTestData = classmethod(datos_ruta.PruebasMiRuta.setUpTestData.__func__)
    motorista = datos_ruta.PruebasMiRuta.motorista
    _crear_solicitud = datos_ruta.PruebasMiRuta._crear_solicitud
    _cliente = datos_ruta.PruebasMiRuta._cliente

    def setUp(self):
        self.ahora = timezone.now()
        self.jornada = JornadaRepartidor.objects.create(
            repartidor=self.motorista, iniciada_en=self.ahora - timedelta(minutes=5),
        )
        self.gps = self._gps()
        self.cliente = self._cliente(self.motorista.usuario)
        self.enterContext(patch("apps.rutas.proveedor_google.urlopen", side_effect=AssertionError("Sin Google real.")))
        self.proveedor = self.enterContext(patch("apps.rutas.ruta_vial.calcular_ruta_google", side_effect=AssertionError("Ordenar no consulta Google.")))

    def _gps(self, longitud="0", *, hace_segundos=0, precision="5", repartidor=None, jornada=None):
        return RegistroUbicacion.objects.create(
            id_cliente=uuid4(), repartidor=repartidor or self.motorista,
            jornada=jornada or self.jornada, latitud="0", longitud=longitud,
            precision_metros=precision,
            registrada_en=self.ahora - timedelta(seconds=hace_segundos),
        )

    def _ubicacion(self, longitud):
        # Coordenadas SINTÉTICAS: no representan lugares reales.
        return Ubicacion.objects.create(
            nombre=f"Punto sintético {longitud}", tipo_ubicacion=self.origen.tipo_ubicacion,
            origen=self.origen.origen, pais=self.empresa.pais, direccion="Solo pruebas",
            latitud="0", longitud=str(longitud),
        )

    def _servicio(self, numero, origen, destino, **opciones):
        solicitud = self._crear_solicitud(numero, **opciones)
        Solicitud.objects.filter(pk=solicitud.pk).update(
            origen=self._ubicacion(origen),
            destino=self._ubicacion(destino) if destino is not None else None,
        )
        return solicitud

    def _sincronizar(self, motivo=VersionRuta.Motivo.ASIGNACION):
        return sincronizar_ruta(self.motorista, motivo)

    def _ids(self, repartidor=None):
        return list(dict.fromkeys(p["solicitud_id"] for p in obtener_paradas_operativas(repartidor or self.motorista)))

    def _leer(self):
        respuesta = self.cliente.get(reverse("rutas:mi-ruta"))
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.proveedor.assert_not_called()
        return respuesta.data

    def test_cercano_nuevo_va_antes_que_antiguo_lejano(self):
        lejano = self._servicio("ORD-LEJANO", ".100", ".101", minutos_atras=20)
        cercano = self._servicio("ORD-CERCANO", ".001", ".002", minutos_atras=1)
        self._sincronizar()
        self.assertEqual(self._ids(), [cercano.pk, lejano.pk])
        datos = self._leer()
        self.assertEqual(datos["orden_tipo"], "CERCANIA_GPS")
        self.assertEqual([p["solicitud_id"] for p in datos["paradas"]], [str(cercano.pk)] * 2 + [str(lejano.pk)] * 2)
        self.assertEqual([p["tipo"] for p in datos["paradas"]], ["RECOLECCION", "ENTREGA"] * 2)
        self.assertEqual([p["orden"] for p in datos["paradas"]], [1, 2, 3, 4])
        self.assertFalse(ConsumoRutasGoogle.objects.exists())

    def test_siguiente_se_compara_desde_cada_parada_y_no_solo_desde_destino(self):
        primera = self._servicio("ORD-A", ".001", ".100", minutos_atras=1)
        segunda = self._servicio("ORD-B", ".002", ".003", minutos_atras=20)
        tercera = self._servicio("ORD-C", ".099", ".098", minutos_atras=10)
        self._sincronizar()
        self.assertEqual(self._ids(), [primera.pk, segunda.pk, tercera.pk])
        self.assertEqual([(p["solicitud_id"], p["tipo"]) for p in obtener_paradas_operativas(self.motorista)], [
            (primera.pk, "RECOLECCION"), (segunda.pk, "RECOLECCION"), (segunda.pk, "ENTREGA"),
            (tercera.pk, "RECOLECCION"), (tercera.pk, "ENTREGA"), (primera.pk, "ENTREGA"),
        ])

    def test_nueva_asignacion_reordena_si_ningun_servicio_ha_comenzado(self):
        anterior = self._servicio("ORD-ANTERIOR", ".100", ".101")
        ruta = self._sincronizar()
        historico = list(ruta.versiones.get(numero=1).paradas.values_list("id", "solicitud_id", "orden"))
        nueva = self._servicio("ORD-NUEVA", ".001", ".002", minutos_atras=0)
        self._sincronizar()
        self.assertEqual(self._ids(), [nueva.pk, anterior.pk])
        self.assertEqual(ruta.versiones.count(), 2)
        self.assertEqual(list(ruta.versiones.get(numero=1).paradas.values_list("id", "solicitud_id", "orden")), historico)

    def test_no_interrumpe_parada_de_recoleccion_en_curso(self):
        iniciada = self._servicio("ORD-INICIADA", ".100", ".101", estado=EstadoSolicitud.HACIA_RECOLECCION)
        self._sincronizar()
        nueva = self._servicio("ORD-NUEVA", ".001", ".002", minutos_atras=0)
        for estado in (EstadoSolicitud.HACIA_RECOLECCION, EstadoSolicitud.EN_RECOLECCION):
            with self.subTest(estado=estado):
                Solicitud.objects.filter(pk=iniciada.pk).update(estado=estado)
                self._sincronizar(VersionRuta.Motivo.CAMBIO_ESTADO)
                self.assertEqual(self._ids(), [iniciada.pk, nueva.pk])

    def test_pendientes_se_ordenan_desde_destino_del_servicio_fijo(self):
        iniciada = self._servicio("ORD-INICIADA", ".200", ".100", estado=EstadoSolicitud.HACIA_RECOLECCION)
        self._sincronizar()
        junto_al_gps = self._servicio("ORD-JUNTO-GPS", ".001", ".002", minutos_atras=1)
        junto_al_destino = self._servicio("ORD-JUNTO-DESTINO", ".099", ".098", minutos_atras=0)
        self._sincronizar()
        self.assertEqual(self._ids(), [iniciada.pk, junto_al_destino.pk, junto_al_gps.pk])

    def test_gps_y_lecturas_no_reordenan_ni_escriben(self):
        cercana = self._servicio("ORD-CERCA", ".001", ".002", minutos_atras=1)
        lejana = self._servicio("ORD-LEJOS", ".100", ".101", minutos_atras=20)
        ruta = self._sincronizar()
        RegistroUbicacion.objects.filter(pk=self.gps.pk).update(longitud=".100")
        for _ in range(2):
            with CaptureQueriesContext(connection) as consultas:
                datos = self._leer()
            self.assertTrue(all(c["sql"].lstrip().upper().startswith("SELECT") for c in consultas))
            self.assertEqual(datos["proxima_parada"]["solicitud_id"], str(cercana.pk))
            self.assertEqual(self._ids(), [cercana.pk, lejana.pk])
        self.assertEqual(ruta.versiones.count(), 1)

    def test_sin_cambio_servicios_no_vuelve_a_medir_gps_al_sincronizar(self):
        self._servicio("ORD-ESTABLE", ".100", ".101")
        ruta = self._sincronizar()
        with patch("apps.rutas.servicios.posiciones_vigentes") as posiciones:
            self._sincronizar(VersionRuta.Motivo.CAMBIO_ESTADO)
        posiciones.assert_not_called()
        self.assertEqual(ruta.versiones.count(), 1)

    def test_recoleccion_intercala_otro_servicio_antes_de_entrega_lejana(self):
        primera = self._servicio("ORD-PRIMERA", ".001", ".100")
        segunda = self._servicio("ORD-SEGUNDA", ".002", ".003", minutos_atras=0)
        self._sincronizar()
        Solicitud.objects.filter(pk=primera.pk).update(estado=EstadoSolicitud.RECOLECTADA)
        self._gps(".002")
        self._sincronizar(VersionRuta.Motivo.CAMBIO_ESTADO)
        paradas = obtener_paradas_operativas(self.motorista)
        self.assertEqual([(p["solicitud_id"], p["tipo"]) for p in paradas],
                         [(segunda.pk, "RECOLECCION"), (segunda.pk, "ENTREGA"), (primera.pk, "ENTREGA")])

    def test_finalizar_servicio_reordena_pendientes_desde_gps_actual(self):
        primera = self._servicio("ORD-PRIMERA", ".001", ".002")
        segunda = self._servicio("ORD-SEGUNDA", ".010", ".011", minutos_atras=2)
        tercera = self._servicio("ORD-TERCERA", ".100", ".101", minutos_atras=1)
        self._sincronizar()
        self.assertEqual(self._ids(), [primera.pk, segunda.pk, tercera.pk])
        RegistroUbicacion.objects.filter(pk=self.gps.pk).update(longitud=".100")
        Solicitud.objects.filter(pk=primera.pk).update(estado=EstadoSolicitud.ENTREGADA)
        self._sincronizar(VersionRuta.Motivo.CAMBIO_ESTADO)
        self.assertEqual(self._ids(), [tercera.pk, segunda.pk])

    def test_cancelar_fallar_o_reasignar_retirado_replanifica(self):
        primera = self._servicio("ORD-RETIRADA", ".001", ".002")
        segunda = self._servicio("ORD-PENDIENTE", ".010", ".011")
        for estado in (EstadoSolicitud.CANCELADA, EstadoSolicitud.RECOLECCION_FALLIDA, EstadoSolicitud.ENTREGA_FALLIDA):
            with self.subTest(estado=estado):
                Solicitud.objects.filter(pk=primera.pk).update(estado=EstadoSolicitud.ASIGNADA)
                self._sincronizar()
                Solicitud.objects.filter(pk=primera.pk).update(estado=estado)
                self._sincronizar(VersionRuta.Motivo.CANCELACION)
                self.assertEqual(self._ids(), [segunda.pk])

    def test_sin_gps_inicial_respaldo_por_antiguedad(self):
        RegistroUbicacion.objects.filter(pk=self.gps.pk).update(precision_metros=None)
        vieja = self._servicio("ORD-VIEJA", ".100", ".101", minutos_atras=20)
        self._servicio("ORD-NUEVA", ".001", ".002", minutos_atras=0)
        self._sincronizar()
        self.assertEqual(self._ids()[0], vieja.pk)

    def test_gps_vencido_futuro_o_impreciso_no_reordena(self):
        vieja = self._servicio("ORD-VIEJA", ".100", ".101", minutos_atras=20)
        nueva = self._servicio("ORD-NUEVA", ".001", ".002", minutos_atras=0)
        for valores in ({"registrada_en": self.ahora - timedelta(seconds=121)},
                        {"registrada_en": self.ahora + timedelta(minutes=1)},
                        {"precision_metros": None}, {"precision_metros": "51"}):
            with self.subTest(valores=valores):
                RegistroUbicacion.objects.filter(pk=self.gps.pk).update(
                    registrada_en=self.ahora, precision_metros="5",
                )
                RegistroUbicacion.objects.filter(pk=self.gps.pk).update(**valores)
                self.assertFalse(posiciones_vigentes().filter(repartidor=self.motorista).exists())
        self._sincronizar()
        self.assertEqual(self._ids(), [vieja.pk, nueva.pk])

    def test_gps_no_vigente_preserva_orden_guardado_y_anexa_nuevos(self):
        lejana = self._servicio("ORD-LEJANA", ".100", ".101", minutos_atras=20)
        cercana = self._servicio("ORD-CERCANA", ".001", ".002", minutos_atras=10)
        self._sincronizar()
        RegistroUbicacion.objects.filter(pk=self.gps.pk).update(precision_metros=None)
        nueva = self._servicio("ORD-NUEVA", ".0001", ".0002", minutos_atras=0)
        self._sincronizar()
        self.assertEqual(self._ids(), [cercana.pk, lejana.pk, nueva.pk])

    def test_jornada_cerrada_no_aporta_gps(self):
        JornadaRepartidor.objects.filter(pk=self.jornada.pk).update(estado="FINALIZADA", finalizada_en=self.ahora)
        vieja = self._servicio("ORD-VIEJA", ".100", ".101", minutos_atras=20)
        self._servicio("ORD-NUEVA", ".001", ".002", minutos_atras=0)
        self._sincronizar()
        self.assertEqual(self._ids()[0], vieja.pk)

    def test_no_utiliza_gps_ni_servicios_de_otro_motorista(self):
        otro = self.motoristas[1]
        jornada = JornadaRepartidor.objects.create(repartidor=otro)
        self._gps(".100", repartidor=otro, jornada=jornada)
        self._servicio("ORD-AJENA", ".0001", ".0002", repartidor=otro)
        cercana = self._servicio("ORD-CERCANA", ".001", ".002", minutos_atras=1)
        lejana = self._servicio("ORD-LEJANA", ".100", ".101", minutos_atras=20)
        self._sincronizar()
        self.assertEqual(self._ids(), [cercana.pk, lejana.pk])

    def test_empates_utilizan_antiguedad_e_identificador(self):
        nueva = self._servicio("ORD-NUEVA", ".001", ".002", minutos_atras=0)
        vieja = self._servicio("ORD-VIEJA", ".001", ".002", minutos_atras=20)
        self._sincronizar()
        self.assertEqual(self._ids(), [vieja.pk, nueva.pk])
        Solicitud.objects.filter(pk__in=[vieja.pk, nueva.pk]).update(asignada_en=self.ahora)
        tercera = self._servicio("ORD-TERCERA", ".001", ".002", minutos_atras=0)
        self._sincronizar()
        self.assertEqual(self._ids()[:2], sorted([vieja.pk, nueva.pk], key=str))
        self.assertEqual(self._ids()[2], tercera.pk)

    def test_prioritario_recogido_precede_servicio_normal_iniciado(self):
        self._servicio("ORD-NORMAL", ".001", ".002", estado=EstadoSolicitud.HACIA_RECOLECCION)
        prioritaria = self._servicio("ORD-PRIORITARIA", ".100", ".101", prioridad=PrioridadSolicitud.PRIORITARIA, estado=EstadoSolicitud.RECOLECTADA)
        self._sincronizar()
        self.assertEqual(self._ids()[0], prioritaria.pk)
        self.assertEqual(self._leer()["proxima_parada"]["tipo"], "ENTREGA")

    def test_especial_recogido_conserva_exclusividad_sin_inventar_destino(self):
        normal = self._servicio("ORD-NORMAL", ".001", ".002")
        especial = self._servicio("ORD-ESPECIAL", ".100", None, modalidad=ModalidadSolicitud.ESPECIAL, estado=EstadoSolicitud.RECOLECTADA)
        self._sincronizar()
        self.assertEqual(self._ids(), [especial.pk, normal.pk])
        datos = self._leer()
        self.assertEqual(datos["ruta_vial"]["estado"], "SOLO_KILOMETROS")
        self.assertIsNone(datos["proxima_parada"]["ubicacion"])

    def test_especial_pendiente_no_inventa_coordenadas_para_ordenar_lo_posterior(self):
        vieja = self._servicio("ORD-VIEJA", ".100", ".101", minutos_atras=20)
        nueva = self._servicio("ORD-NUEVA", ".002", ".003", minutos_atras=1)
        especial = self._servicio("ORD-ESPECIAL", ".001", None, modalidad=ModalidadSolicitud.ESPECIAL, minutos_atras=0)
        self._sincronizar()
        self.assertEqual(self._ids(), [especial.pk, vieja.pk, nueva.pk])

    def test_gps_posterior_no_reordena_lectura_sin_version_inicial(self):
        vieja = self._servicio("ORD-VIEJA", ".100", ".101", minutos_atras=20)
        self._servicio("ORD-NUEVA", ".001", ".002", minutos_atras=0)
        datos = self._leer()
        self.assertEqual(datos["proxima_parada"]["solicitud_id"], str(vieja.pk))
        self.assertFalse(VersionRuta.objects.exists())

    def test_cinco_servicios_se_leen_en_dos_consultas_sin_n_mas_uno(self):
        for indice in range(5):
            self._servicio(f"ORD-CINCO-{indice}", f".00{indice + 1}", f".00{indice + 2}")
        self._sincronizar()
        with self.assertNumQueries(2):
            paradas = obtener_paradas_operativas(self.motorista)
        self.assertEqual(len(paradas), 10)

    def test_rollback_no_publica_reordenamiento_parcial(self):
        anterior = self._servicio("ORD-ANTERIOR", ".100", ".101")
        ruta = self._sincronizar()
        with self.assertRaisesMessage(RuntimeError, "Prueba de rollback"):
            with transaction.atomic():
                self._servicio("ORD-NUEVA", ".001", ".002", minutos_atras=0)
                self._sincronizar()
                self.assertEqual(ruta.versiones.count(), 2)
                raise RuntimeError("Prueba de rollback")
        self.assertEqual(ruta.versiones.count(), 1)
        self.assertEqual(self._ids(), [anterior.pk])

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_comparte_orden_sin_mezclar_despliegues(self):
        self.test_cercano_nuevo_va_antes_que_antiguo_lejano()

    def test_reasignacion_elimina_servicio_de_ruta_anterior(self):
        solicitud = self._servicio("ORD-REASIGNADA", ".001", ".002")
        self._sincronizar()
        AsignacionSolicitud.objects.filter(solicitud=solicitud).update(estado=EstadoAsignacionSolicitud.REASIGNADA, finalizada_en=self.ahora)
        Solicitud.objects.filter(pk=solicitud.pk).update(repartidor_asignado=self.motoristas[1])
        AsignacionSolicitud.objects.create(solicitud=solicitud, repartidor=self.motoristas[1], asignada_por=self.administrador)
        self._sincronizar(VersionRuta.Motivo.REASIGNACION)
        sincronizar_ruta(self.motoristas[1], VersionRuta.Motivo.REASIGNACION)
        self.assertEqual(self._ids(), [])
        self.assertEqual(self._ids(self.motoristas[1]), [solicitud.pk])

    def test_trazado_anterior_no_se_muestra_tras_reordenar(self):
        self._servicio("ORD-ANTERIOR", ".100", ".101")
        ruta = self._sincronizar()
        CalculoRutaVial.objects.create(
            version=ruta.versiones.get(), estado="CALCULADA", token_intento=uuid4(),
            iniciada_en=self.ahora, calculada_en=self.ahora, expira_en=self.ahora + timedelta(hours=1),
            origen_gps={"latitud": "0", "longitud": "0"},
            paradas_calculadas=firma_paradas(obtener_paradas_operativas(self.motorista)),
            polilinea_codificada="????", polilineas_tramos=["????", "??????"],
        )
        self.assertTrue(self._leer()["mapa"]["mostrar_trazado"])
        self._servicio("ORD-NUEVA", ".001", ".002", minutos_atras=0)
        self._sincronizar()
        datos = self._leer()
        self.assertFalse(datos["mapa"]["mostrar_trazado"])
        self.assertIsNone(datos["ruta_vial"]["polilinea_codificada"])
        self.assertEqual(datos["ruta_vial"]["tramos"], [])
        self.assertEqual(CalculoRutaVial.objects.count(), 1)
        self.assertFalse(ConsumoRutasGoogle.objects.exists())

    def test_llegada_automatica_utiliza_primero_del_orden_guardado(self):
        lejana = self._servicio("ORD-LEJANA", ".100", ".101", minutos_atras=20)
        cercana = self._servicio("ORD-CERCANA", ".001", ".002", minutos_atras=10)
        self._sincronizar()
        self.motorista.estado_operativo = "ON_ROUTE"
        self.motorista.save(update_fields=("estado_operativo", "actualizado_en"))
        Solicitud.objects.filter(pk=cercana.pk).update(estado=EstadoSolicitud.HACIA_RECOLECCION)
        evento = EventoSolicitud.objects.create(
            solicitud=cercana, repartidor=self.motorista, realizado_por=self.motorista.usuario,
            tipo=TipoEventoSolicitud.HACIA_RECOLECCION,
        )
        EventoSolicitud.objects.filter(pk=evento.pk).update(creado_en=self.ahora - timedelta(seconds=60))
        self._sincronizar(VersionRuta.Motivo.CAMBIO_ESTADO)
        for segundos in (15, 8, 1):
            punto = self._gps(".001", hace_segundos=segundos)
            RegistroUbicacion.objects.filter(pk=punto.pk).update(creado_en=self.ahora - timedelta(seconds=segundos))
        RegistroUbicacion.objects.filter(pk=self.gps.pk).update(registrada_en=self.ahora - timedelta(minutes=2))
        with patch("apps.seguimiento.llegadas.timezone.now", return_value=self.ahora):
            llegada = detectar_llegada(self.motorista.usuario, self.motorista.pk, self.jornada.pk)
        self.assertIsNotNone(llegada)
        self.assertEqual(llegada["solicitud_id"], str(cercana.pk))
        lejana.refresh_from_db()
        self.assertEqual(lejana.estado, EstadoSolicitud.ASIGNADA)
