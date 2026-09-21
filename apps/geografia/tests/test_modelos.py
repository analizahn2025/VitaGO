from django.test import SimpleTestCase

from apps.geografia.models import Pais


class PruebasModeloPais(SimpleTestCase):
    def test_normaliza_codigos_del_pais(self):
        pais = Pais(
            iso2="hn",
            iso3="hnd",
            nombre="Honduras",
            codigo_telefonico=" +504 ",
            codigo_moneda="hnl",
            zona_horaria_predeterminada=" America/Tegucigalpa ",
        )

        pais.clean()

        self.assertEqual(pais.iso2, "HN")
        self.assertEqual(pais.iso3, "HND")
        self.assertEqual(pais.codigo_moneda, "HNL")
        self.assertEqual(pais.codigo_telefonico, "+504")
        self.assertEqual(
            pais.zona_horaria_predeterminada,
            "America/Tegucigalpa",
        )
