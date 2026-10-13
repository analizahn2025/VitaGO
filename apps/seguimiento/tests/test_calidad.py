from datetime import timedelta
from decimal import Decimal

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from apps.seguimiento.calidad import medir_puntos


class PruebasCalidadGPS(SimpleTestCase):
    def setUp(self):
        self.inicio = timezone.now()

    def punto(self, segundo, latitud, precision=8, velocidad=None):
        return (Decimal(str(latitud)), Decimal("-87"), precision, velocidad,
                self.inicio + timedelta(seconds=segundo))

    def test_corte_de_senal_no_se_inventa_como_linea_recta(self):
        medicion = medir_puntos([
            self.punto(0, 14), self.punto(5, 14.0001),
            self.punto(120, 14.01), self.punto(125, 14.0101),
        ])
        self.assertEqual(medicion["huecos_detectados"], 1)
        self.assertEqual(medicion["segundos_cubiertos"], 10)
        self.assertGreater(medicion["kilometros"], Decimal("0.020"))
        self.assertLess(medicion["kilometros"], Decimal("0.030"))

    def test_telefono_parado_con_deriva_no_acumula_kilometros(self):
        puntos = [self.punto(i * 5, 14 + ((i % 3) - 1) * 0.00001, precision=15) for i in range(100)]
        medicion = medir_puntos(puntos)
        self.assertEqual(medicion["kilometros"], Decimal("0.000"))
        self.assertEqual(medicion["segmentos_validos"], 99)

    def test_caminar_despacio_acumula_desplazamiento_desde_ancla(self):
        medicion = medir_puntos([self.punto(i * 5, 14 + i * 0.00001, precision=2) for i in range(21)])
        self.assertGreater(medicion["kilometros"], Decimal("0.015"))

    def test_punto_invalido_rompe_tramo_en_vez_de_puentearlo(self):
        medicion = medir_puntos([
            self.punto(0, 14), self.punto(5, 14.0001, precision=500), self.punto(10, 14.0002),
        ])
        self.assertEqual(medicion["kilometros"], Decimal("0.000"))
        self.assertEqual(medicion["puntos_descartados"], 1)

    def test_salto_imposible_no_cuenta_y_luego_recupera(self):
        medicion = medir_puntos([
            self.punto(0, 14), self.punto(5, 15), self.punto(10, 14), self.punto(15, 14.0001),
        ])
        self.assertEqual(medicion["puntos_descartados"], 1)
        self.assertLess(medicion["kilometros"], Decimal("0.020"))

    @override_settings(INTERVALO_GPS_MAXIMO_SEGUNDOS=3)
    def test_tolerancia_es_configurable(self):
        self.assertEqual(medir_puntos([self.punto(0, 14), self.punto(5, 14.0001)])["segmentos_validos"], 0)
