"""Los cierres comparten persistencia, no sus condiciones de autorización."""

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.db import transaction
from django.http import Http404
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.jornadas.servicios import finalizar_jornada, iniciar_jornada, registrar_cierre_jornada
from apps.jornadas.tests import test_jornadas as datos_jornadas
from apps.repartidores.models import HistorialEstadoRepartidor
from apps.rutas.models import RutaRepartidor
from apps.seguimiento.models import RevisionKilometraje
from apps.solicitudes.contingencias import cerrar_jornada_vencida
from apps.solicitudes.models import AsignacionSolicitud, Solicitud
from apps.solicitudes.vigencia import limite_dia_operativo
from apps.usuarios.models import RolUsuario


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasCierreCompartido(TestCase):
    setUpTestData = classmethod(datos_jornadas.PruebasJornadas.setUpTestData.__func__)

    def setUp(self):
        self.repartidor = self.repartidores[0]
        self.jornada = iniciar_jornada(self.repartidor.usuario, {})
        self.jornada.iniciada_en = timezone.now() - timedelta(hours=1)
        self.jornada.save()
        self.repartidor.refresh_from_db()
        self.ruta = RutaRepartidor.objects.create(repartidor=self.repartidor, jornada=self.jornada)
        self.corte = limite_dia_operativo(self.jornada.iniciada_en, self.empresa)
        self.historial_inicial = HistorialEstadoRepartidor.objects.count()

    def test_manual_delega_y_conserva_coordenadas_manifiesto_y_autor(self):
        datos = {"latitud": Decimal("14.082300"), "longitud": Decimal("-87.182100"), "sesiones_gps": []}
        with patch("apps.jornadas.servicios.registrar_cierre_jornada", wraps=registrar_cierre_jornada) as registrar:
            finalizada = finalizar_jornada(self.repartidor.usuario, self.jornada.pk, datos)
        registrar.assert_called_once()
        self.assertEqual(registrar.call_args.kwargs["datos_cierre"], datos)
        self.assertEqual((finalizada.latitud_fin, finalizada.longitud_fin), (datos["latitud"], datos["longitud"]))
        self.assertTrue(finalizada.calidad_kilometraje["sincronizacion_verificada"])
        revision = RevisionKilometraje.objects.get(jornada=self.jornada)
        self.assertEqual(revision.motivo, "CIERRE")
        historial = HistorialEstadoRepartidor.objects.get(motivo="Finalización de jornada.")
        self.assertEqual(historial.realizado_por_id, self.repartidor.usuario_id)
        self.ruta.refresh_from_db()
        self.assertEqual(self.ruta.estado, "FINALIZADA")

    def test_automatico_delega_con_corte_exacto_sin_autor_ni_coordenadas_inventadas(self):
        with patch("apps.jornadas.servicios.registrar_cierre_jornada", wraps=registrar_cierre_jornada) as registrar:
            self.assertTrue(cerrar_jornada_vencida(self.jornada.pk, self.corte + timedelta(hours=3)))
        registrar.assert_called_once()
        self.assertIsNone(registrar.call_args.args[2])
        self.assertEqual(registrar.call_args.kwargs["finalizada_en"], self.corte)
        self.jornada.refresh_from_db()
        self.ruta.refresh_from_db()
        self.assertEqual((self.jornada.finalizada_en, self.ruta.finalizada_en), (self.corte, self.corte))
        self.assertIsNone(self.jornada.latitud_fin)
        self.assertIsNone(self.jornada.longitud_fin)
        self.assertEqual(self.jornada.calidad_kilometraje["estado"], "SIN_VERIFICAR")
        self.assertEqual(RevisionKilometraje.objects.get(jornada=self.jornada).motivo, "FIN_DIA")
        historial = HistorialEstadoRepartidor.objects.get(motivo="Fin del día operativo.")
        self.assertIsNone(historial.realizado_por_id)

    def test_manual_sin_manifesto_no_se_confunde_con_confirmacion_vacia(self):
        finalizada = finalizar_jornada(self.repartidor.usuario, self.jornada.pk, {})
        self.assertFalse(finalizada.calidad_kilometraje["sincronizacion_verificada"])
        self.assertEqual(finalizada.calidad_kilometraje["estado"], "SIN_VERIFICAR")

    def test_no_delega_si_hay_asignaciones_activas_en_ningun_tipo_de_cierre(self):
        solicitud = Solicitud.objects.create(cantidad_tubos=1, numero="BLOQUEA-CIERRE", empresa=self.empresa,
            solicitada_por=self.administrador, repartidor_asignado=self.repartidor,
            prioridad="NORMAL", origen=self.origen, destino=self.destino, estado="ASSIGNED")
        AsignacionSolicitud.objects.create(solicitud=solicitud, repartidor=self.repartidor, asignada_por=self.administrador)
        with patch("apps.jornadas.servicios.registrar_cierre_jornada") as registrar:
            with self.assertRaises(ValidationError):
                finalizar_jornada(self.repartidor.usuario, self.jornada.pk, {})
            self.assertFalse(cerrar_jornada_vencida(self.jornada.pk, self.corte))
        registrar.assert_not_called()

    def test_no_delega_cierre_manual_ajeno_o_sin_permiso(self):
        with patch("apps.jornadas.servicios.registrar_cierre_jornada") as registrar:
            with self.assertRaises(Http404):
                finalizar_jornada(self.repartidores[1].usuario, self.jornada.pk, {})
            RolUsuario.objetos.filter(usuario_id=self.repartidor.usuario_id).update(
                activo=False, revocado_en=timezone.now(), revocado_por=self.administrador,
            )
            with self.assertRaises(PermissionDenied):
                finalizar_jornada(self.repartidor.usuario, self.jornada.pk, {})
        registrar.assert_not_called()

    def test_repetir_cierre_no_duplica_revision_ni_historial(self):
        finalizar_jornada(self.repartidor.usuario, self.jornada.pk, {})
        with self.assertRaises(ValidationError):
            finalizar_jornada(self.repartidor.usuario, self.jornada.pk, {})
        self.assertFalse(cerrar_jornada_vencida(self.jornada.pk, self.corte))
        self.assertEqual(RevisionKilometraje.objects.filter(jornada=self.jornada).count(), 1)
        self.assertEqual(HistorialEstadoRepartidor.objects.count(), self.historial_inicial + 1)

    def test_fallo_al_cerrar_ruta_revierte_toda_la_operacion_en_ambos_flujos(self):
        for modo in ("manual", "automatico"):
            with self.subTest(modo=modo):
                with patch("apps.rutas.servicios.sincronizar_ruta", side_effect=RuntimeError("Fallo simulado")):
                    with self.assertRaises(RuntimeError):
                        if modo == "manual":
                            finalizar_jornada(self.repartidor.usuario, self.jornada.pk, {})
                        else:
                            cerrar_jornada_vencida(self.jornada.pk, self.corte)
                self.jornada.refresh_from_db()
                self.repartidor.refresh_from_db()
                self.ruta.refresh_from_db()
                self.assertEqual((self.jornada.estado, self.ruta.estado), ("ACTIVA", "ACTIVA"))
                self.assertIsNone(self.jornada.finalizada_en)
                self.assertEqual(self.repartidor.estado_operativo, "AVAILABLE")
                self.assertFalse(RevisionKilometraje.objects.filter(jornada=self.jornada).exists())
                self.assertEqual(HistorialEstadoRepartidor.objects.count(), self.historial_inicial)

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_no_delega_cierre_automatico(self):
        with patch("apps.jornadas.servicios.registrar_cierre_jornada") as registrar:
            self.assertFalse(cerrar_jornada_vencida(self.jornada.pk, self.corte))
        registrar.assert_not_called()


class PruebasTransaccionCierreCompartido(SimpleTestCase):
    def test_no_admite_cierre_sin_transaccion(self):
        with patch("apps.jornadas.servicios.transaction.get_connection", return_value=SimpleNamespace(in_atomic_block=False)):
            with self.assertRaises(RuntimeError):
                registrar_cierre_jornada(object(), object(), None, finalizada_en=timezone.now())
