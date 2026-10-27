"""Caducidad a medianoche y archivado recuperable, sin datos operativos reales."""

import json
from datetime import datetime, timedelta, timezone as zona_fecha
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.http import Http404
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.evidencias.models import EvidenciaSolicitud
from apps.notificaciones.models import NotificacionUsuario
from apps.notificaciones.selectores import contar_no_leidas, listar_notificaciones, obtener_notificacion_propia
from apps.notificaciones.servicios import archivar_notificaciones_vencidas, marcar_notificacion_leida
from apps.notificaciones.vigencia import limites_dia_operativo
from apps.seguimiento.models import RegistroUbicacion
from apps.solicitudes.models import EventoSolicitud, Solicitud
from apps.solicitudes.tests import test_asignaciones as datos_asignaciones


@override_settings(TIME_ZONE="America/Tegucigalpa", MODO_APLICACION="CORPORATIVO")
class PruebasArchivadoDiario(TestCase):
    setUpTestData = classmethod(datos_asignaciones.PruebasAsignacionesSolicitud.setUpTestData.__func__)
    _registrar_gps = datos_asignaciones.PruebasAsignacionesSolicitud._registrar_gps

    def setUp(self):
        datos_asignaciones.PruebasAsignacionesSolicitud.setUp(self)
        self.ahora = datetime(2026, 10, 23, 12, tzinfo=zona_fecha.utc)
        reloj = patch("apps.notificaciones.vigencia.timezone.now", return_value=self.ahora)
        self.reloj = reloj.start()
        self.addCleanup(reloj.stop)
        bloqueo = patch("apps.rutas.proveedor_google.urlopen", side_effect=AssertionError("Archivado sin Google."))
        bloqueo.start()
        self.addCleanup(bloqueo.stop)
        self.inicio, self.fin = limites_dia_operativo()
        self.usuario = self.repartidores[0].usuario
        self.otro = self.repartidores[1].usuario
        self.cliente = APIClient()
        self.cliente.force_authenticate(self.usuario)

    def _aviso(self, fecha, *, usuario=None, leida=False, archivada=False):
        evento = EventoSolicitud.objects.create(
            solicitud=self.solicitud, tipo="ASIGNADA", realizado_por=self.administrador,
        )
        aviso = NotificacionUsuario.objects.create(
            usuario=usuario or self.usuario, solicitud=self.solicitud, evento=evento,
            tipo="SOLICITUD_ASIGNADA", titulo="Aviso de prueba", mensaje="Servicio de prueba",
            leida_en=fecha if leida else None,
            archivada_en=fecha if archivada else None,
        )
        NotificacionUsuario.objects.filter(pk=aviso.pk).update(creado_en=fecha, actualizado_en=fecha)
        aviso.refresh_from_db()
        return aviso

    def test_solo_avisos_del_dia_visibles_sin_ejecutar_tarea(self):
        viejo = self._aviso(self.inicio - timedelta(seconds=1))
        actual = self._aviso(self.inicio)
        self.assertEqual(list(listar_notificaciones(self.usuario)), [actual])
        self.assertEqual(contar_no_leidas(self.usuario), 1)
        viejo.refresh_from_db()
        self.assertIsNone(viejo.archivada_en)
        self.assertIsNone(viejo.leida_en)

    def test_caduca_exactamente_a_medianoche_y_no_antes(self):
        aviso = self._aviso(self.inicio - timedelta(microseconds=1))
        self.reloj.return_value = self.inicio - timedelta(microseconds=1)
        self.assertEqual(contar_no_leidas(self.usuario), 1)
        self.reloj.return_value = self.inicio
        self.assertEqual(contar_no_leidas(self.usuario), 0)
        self.assertFalse(listar_notificaciones(self.usuario).exists())
        self.assertTrue(NotificacionUsuario.objects.filter(pk=aviso.pk).exists())

    def test_avisos_futuros_no_entran_en_listado_ni_conteo(self):
        self._aviso(self.fin)
        self.assertFalse(listar_notificaciones(self.usuario).exists())
        self.assertEqual(contar_no_leidas(self.usuario), 0)

    def test_avisos_archivados_no_reaparecen_aunque_sean_del_dia(self):
        self._aviso(self.inicio, archivada=True)
        self.assertEqual(contar_no_leidas(self.usuario), 0)
        self.assertFalse(listar_notificaciones(self.usuario).exists())

    def test_lectura_y_propiedad_se_conservan(self):
        actual = self._aviso(self.inicio)
        self._aviso(self.inicio, leida=True)
        self._aviso(self.inicio, usuario=self.otro)
        self._aviso(self.inicio - timedelta(days=1), leida=True)
        self.assertEqual(listar_notificaciones(self.usuario).count(), 2)
        self.assertEqual(contar_no_leidas(self.usuario), 1)
        self.assertEqual(obtener_notificacion_propia(self.usuario, actual.pk).pk, actual.pk)
        with self.assertRaises(Http404):
            obtener_notificacion_propia(self.otro, actual.pk)

    def test_listado_y_conteo_http_tienen_el_mismo_corte(self):
        actual = self._aviso(self.inicio)
        self._aviso(self.inicio - timedelta(days=7))
        listado = self.cliente.get("/api/v1/notificaciones/")
        conteo = self.cliente.get("/api/v1/notificaciones/conteo-no-leidas/")
        self.assertEqual(listado.status_code, 200)
        self.assertEqual(listado.data["conteo"], 1)
        self.assertEqual(str(listado.data["resultados"][0]["id"]), str(actual.pk))
        self.assertEqual(conteo.data, {"conteo_no_leidas": 1})
        self.assertEqual(set(listado.data["resultados"][0]), {
            "id", "tipo", "titulo", "mensaje", "solicitud_id", "ruta", "enlace_profundo",
            "leida", "leida_en", "creado_en",
        })

    def test_aviso_vencido_no_puede_marcarse_leido_por_http(self):
        aviso = self._aviso(self.inicio - timedelta(microseconds=1))
        respuesta = self.cliente.post(f"/api/v1/notificaciones/{aviso.pk}/marcar-leida/")
        self.assertEqual(respuesta.status_code, 404)
        aviso.refresh_from_db()
        self.assertIsNone(aviso.leida_en)

    def test_servicio_revalida_aviso_obtenido_antes_del_corte(self):
        aviso = self._aviso(self.inicio - timedelta(microseconds=1))
        self.reloj.return_value = self.inicio - timedelta(microseconds=1)
        previo = obtener_notificacion_propia(self.usuario, aviso.pk)
        self.reloj.return_value = self.inicio
        with self.assertRaises(Http404):
            marcar_notificacion_leida(self.usuario, previo)
        aviso.refresh_from_db()
        self.assertIsNone(aviso.leida_en)

    def test_revalida_si_el_bloqueo_cruza_medianoche(self):
        aviso = self._aviso(self.inicio)
        siguientes = (self.fin, self.fin + timedelta(days=1))
        with patch("apps.notificaciones.selectores.limites_dia_operativo", return_value=siguientes):
            with self.assertRaises(Http404):
                marcar_notificacion_leida(self.usuario, aviso)
        aviso.refresh_from_db()
        self.assertIsNone(aviso.leida_en)

    def test_marcar_vigente_es_idempotente(self):
        aviso = self._aviso(self.inicio)
        ruta = f"/api/v1/notificaciones/{aviso.pk}/marcar-leida/"
        primera = self.cliente.post(ruta)
        self.reloj.return_value = self.ahora + timedelta(minutes=1)
        segunda = self.cliente.post(ruta)
        self.assertEqual(primera.status_code, 200)
        self.assertEqual(segunda.status_code, 200)
        self.assertEqual(primera.data["leida_en"], segunda.data["leida_en"])
        self.assertEqual(contar_no_leidas(self.usuario), 0)

    def test_archiva_todos_los_dias_anteriores_y_preserva_lectura(self):
        viejos = [self._aviso(self.inicio - timedelta(days=d), leida=(d == 1)) for d in (1, 3, 90)]
        actual = self._aviso(self.inicio)
        futuro = self._aviso(self.fin)
        resultado = archivar_notificaciones_vencidas()
        self.assertEqual(resultado["avisos_vencidos"], 3)
        self.assertEqual(resultado["fecha_operativa"], "2026-10-23")
        self.assertEqual(resultado["zona_horaria_operativa"], "America/Tegucigalpa")
        self.assertEqual(resultado["siguiente_corte_en"], self.fin.isoformat())
        for viejo in viejos:
            leida = viejo.leida_en
            viejo.refresh_from_db()
            self.assertEqual(viejo.archivada_en, self.ahora)
            self.assertEqual(viejo.leida_en, leida)
        actual.refresh_from_db()
        futuro.refresh_from_db()
        self.assertIsNone(actual.archivada_en)
        self.assertIsNone(futuro.archivada_en)

    def test_archivado_es_idempotente_y_no_cambia_fecha_de_archivo(self):
        viejo = self._aviso(self.inicio - timedelta(days=5))
        self.assertEqual(archivar_notificaciones_vencidas()["avisos_vencidos"], 1)
        self.reloj.return_value = self.ahora + timedelta(hours=1)
        self.assertEqual(archivar_notificaciones_vencidas()["avisos_vencidos"], 0)
        viejo.refresh_from_db()
        self.assertEqual(viejo.archivada_en, self.ahora)

    def test_simular_no_escribe(self):
        viejo = self._aviso(self.inicio - timedelta(days=1))
        with CaptureQueriesContext(connection) as consultas:
            resultado = archivar_notificaciones_vencidas(simular=True)
        self.assertTrue(resultado["simulacion"])
        self.assertEqual(resultado["avisos_vencidos"], 1)
        self.assertTrue(all(c["sql"].lstrip().startswith("SELECT") for c in consultas))
        viejo.refresh_from_db()
        self.assertIsNone(viejo.archivada_en)

    def test_archiva_avisos_de_todos_los_usuarios(self):
        for usuario in (self.usuario, self.otro, self.administrador):
            self._aviso(self.inicio - timedelta(days=2), usuario=usuario)
        self.assertEqual(archivar_notificaciones_vencidas()["avisos_vencidos"], 3)

    def test_solamente_actualiza_notificaciones_sin_borrar_tablas(self):
        self._aviso(self.inicio - timedelta(days=1))
        modelos = (Solicitud, EventoSolicitud, RegistroUbicacion, EvidenciaSolicitud)
        anteriores = [list(modelo.objects.order_by("pk").values()) for modelo in modelos]
        with CaptureQueriesContext(connection) as consultas:
            archivar_notificaciones_vencidas()
        self.assertEqual(len(consultas), 1)
        self.assertTrue(consultas[0]["sql"].lstrip().startswith('UPDATE "notificaciones_usuario"'))
        self.assertEqual(anteriores, [list(modelo.objects.order_by("pk").values()) for modelo in modelos])

    def test_aviso_reciente_no_caduca_por_antiguedad_de_la_solicitud(self):
        Solicitud.objects.filter(pk=self.solicitud.pk).update(creado_en=self.inicio - timedelta(days=20))
        self._aviso(self.inicio)
        self.assertEqual(contar_no_leidas(self.usuario), 1)
        self.assertEqual(archivar_notificaciones_vencidas()["avisos_vencidos"], 0)

    def test_zona_activada_por_usuario_no_cambia_el_dia_del_servidor(self):
        self.reloj.return_value = self.inicio
        self._aviso(self.inicio)
        with timezone.override("Pacific/Honolulu"):
            self.assertEqual(limites_dia_operativo()[0], self.inicio)
            self.assertEqual(contar_no_leidas(self.usuario), 1)

    @override_settings(TIME_ZONE="UTC")
    def test_se_respeta_otra_zona_del_servidor(self):
        self.reloj.return_value = datetime(2026, 10, 23, 1, tzinfo=zona_fecha.utc)
        self._aviso(datetime(2026, 10, 22, 23, 59, tzinfo=zona_fecha.utc))
        self._aviso(datetime(2026, 10, 23, 0, 0, tzinfo=zona_fecha.utc))
        self.assertEqual(contar_no_leidas(self.usuario), 1)
        self.assertEqual(archivar_notificaciones_vencidas()["zona_horaria_operativa"], "UTC")

    @override_settings(TIME_ZONE="America/New_York")
    def test_limites_respetan_dias_de_23_y_25_horas(self):
        for mes, dia, horas in ((3, 8, 23), (11, 1, 25)):
            with self.subTest(horas=horas):
                inicio, fin = limites_dia_operativo(datetime(2026, mes, dia, 12, tzinfo=zona_fecha.utc))
                self.assertEqual((fin.astimezone(zona_fecha.utc) - inicio.astimezone(zona_fecha.utc)).total_seconds(), horas * 3600)

    def test_comando_rechaza_otro_modo_sin_escribir(self):
        viejo = self._aviso(self.inicio - timedelta(days=1))
        with self.assertRaises(CommandError):
            call_command("archivar_notificaciones_vencidas", modo_esperado="EXTERNO", confirmar=True)
        viejo.refresh_from_db()
        self.assertIsNone(viejo.archivada_en)

    def test_comando_exige_confirmacion_o_simulacion(self):
        with self.assertRaises(CommandError):
            call_command("archivar_notificaciones_vencidas", modo_esperado="CORPORATIVO")

    def test_comando_simulacion_y_confirmacion(self):
        viejo = self._aviso(self.inicio - timedelta(days=1))
        for simular, confirmar in ((True, False), (False, True)):
            salida = StringIO()
            accion = {"simular": True} if simular else {"confirmar": True}
            call_command("archivar_notificaciones_vencidas", modo_esperado="CORPORATIVO", stdout=salida, **accion)
            self.assertEqual(json.loads(salida.getvalue())["avisos_vencidos"], 1)
            viejo.refresh_from_db()
            self.assertEqual(viejo.archivada_en is None, simular)

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_comando_network_solo_con_su_modo_y_enlaces_network(self):
        self._aviso(self.inicio)
        self._aviso(self.inicio - timedelta(days=1))
        salida = StringIO()
        call_command("archivar_notificaciones_vencidas", modo_esperado="EXTERNO", confirmar=True, stdout=salida)
        self.assertEqual(json.loads(salida.getvalue())["avisos_vencidos"], 1)
        respuesta = self.cliente.get("/api/v1/notificaciones/")
        self.assertEqual(respuesta.data["conteo"], 1)
        self.assertTrue(respuesta.data["resultados"][0]["enlace_profundo"].startswith("vitago-network:///"))

    def test_comando_tambien_funciona_sin_stdout_de_pythonw(self):
        from apps.notificaciones.management.commands.archivar_notificaciones_vencidas import Command

        self._aviso(self.inicio - timedelta(days=1))
        comando = Command(stdout=StringIO())
        comando.stdout._out = None
        comando.handle(modo_esperado="CORPORATIVO", confirmar=True, simular=False)
        self.assertEqual(NotificacionUsuario.objects.filter(archivada_en__isnull=False).count(), 1)

    def test_comando_tampoco_admite_confirmacion_falsa_por_codigo(self):
        from apps.notificaciones.management.commands.archivar_notificaciones_vencidas import Command

        viejo = self._aviso(self.inicio - timedelta(days=1))
        for confirmar, simular in ((False, False), (True, True)):
            with self.subTest(confirmar=confirmar, simular=simular), self.assertRaises(CommandError):
                Command().handle(modo_esperado="CORPORATIVO", confirmar=confirmar, simular=simular)
        viejo.refresh_from_db()
        self.assertIsNone(viejo.archivada_en)
