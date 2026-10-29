"""El cierre manual tardío conserva el corte operativo, sin inventar GPS."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.exceptions import ValidationError

from apps.jornadas.servicios import finalizar_jornada
from apps.jornadas.tests import test_cierre_compartido as datos
from apps.seguimiento.models import RevisionKilometraje
from apps.repartidores.models import HistorialEstadoRepartidor


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasCorteManual(TestCase):
    setUpTestData = classmethod(datos.PruebasCierreCompartido.setUpTestData.__func__)
    setUp = datos.PruebasCierreCompartido.setUp

    def _cerrar(self, instante):
        with patch("django.utils.timezone.now", return_value=instante):
            return finalizar_jornada(self.repartidor.usuario, self.jornada.pk, {
                "latitud": Decimal("14.080000"), "longitud": Decimal("-87.180000"),
                "sesiones_gps": [],
            })

    def test_cierre_tardio_usa_corte_sin_coordenadas_actuales(self):
        cerrada = self._cerrar(self.corte + timedelta(minutes=2))
        self.ruta.refresh_from_db()
        self.assertEqual(cerrada.finalizada_en, self.corte)
        self.assertEqual(self.ruta.finalizada_en, self.corte)
        self.assertIsNone(cerrada.latitud_fin)
        self.assertIsNone(cerrada.longitud_fin)
        self.assertEqual(cerrada.calidad_kilometraje["estado"], "SIN_VERIFICAR")
        self.assertEqual(RevisionKilometraje.objects.get(jornada=cerrada).motivo, "FIN_DIA")
        historial = HistorialEstadoRepartidor.objects.get(motivo="Fin del día operativo.")
        self.assertIsNone(historial.realizado_por_id)

    def test_22_exactas_tambien_cierra_por_fin_dia(self):
        self.assertEqual(self._cerrar(self.corte).finalizada_en, self.corte)
        self.assertEqual(RevisionKilometraje.objects.get(jornada=self.jornada).motivo, "FIN_DIA")

    def test_antes_de_22_conserva_cierre_manual(self):
        instante = self.corte - timedelta(seconds=1)
        cerrada = self._cerrar(instante)
        self.assertEqual(cerrada.finalizada_en, instante)
        self.assertIsNotNone(cerrada.latitud_fin)
        self.assertEqual(RevisionKilometraje.objects.get(jornada=cerrada).motivo, "CIERRE")

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_tambien_cierra_a_las_22(self):
        instante = self.corte + timedelta(minutes=2)
        cerrada = self._cerrar(instante)
        self.assertEqual(cerrada.finalizada_en, self.corte)
        self.assertIsNone(cerrada.latitud_fin)
        self.assertEqual(RevisionKilometraje.objects.get(jornada=cerrada).motivo, "FIN_DIA")

    def test_repetir_cierre_tardio_no_duplica_revision(self):
        self._cerrar(self.corte + timedelta(seconds=1))
        with self.assertRaises(ValidationError):
            self._cerrar(self.corte + timedelta(seconds=2))
        self.assertEqual(RevisionKilometraje.objects.filter(jornada=self.jornada).count(), 1)
