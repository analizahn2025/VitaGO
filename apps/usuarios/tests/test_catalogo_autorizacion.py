from importlib import import_module

from django.test import SimpleTestCase


catalogo = import_module(
    "apps.usuarios.migrations.0004_catalogo_inicial_autorizacion"
)


class PruebasCatalogoAutorizacion(SimpleTestCase):
    def test_matriz_contiene_exactamente_los_roles_del_catalogo(self):
        self.assertEqual(set(catalogo.MATRIZ_ROLES), set(catalogo.ROLES))

    def test_matriz_solo_referencia_permisos_del_catalogo(self):
        permisos_definidos = set(catalogo.PERMISOS)

        for permisos_rol in catalogo.MATRIZ_ROLES.values():
            self.assertTrue(permisos_rol)
            self.assertTrue(permisos_rol <= permisos_definidos)

    def test_superadministrador_posee_todos_los_permisos(self):
        self.assertEqual(
            catalogo.MATRIZ_ROLES["SUPERADMINISTRADOR"],
            set(catalogo.PERMISOS),
        )

    def test_roles_corporativos_no_poseen_permisos_de_tarifas(self):
        roles_corporativos = {
            "ADMINISTRADOR_CORPORATIVO",
            "SUPERVISOR_CORPORATIVO",
            "SOLICITANTE_CORPORATIVO",
            "REPARTIDOR_CORPORATIVO",
        }

        for codigo_rol in roles_corporativos:
            permisos = catalogo.MATRIZ_ROLES[codigo_rol]
            self.assertNotIn("tarifa.ver", permisos)
            self.assertNotIn("tarifa.administrar", permisos)

    def test_roles_declaran_al_menos_un_alcance(self):
        for datos_rol in catalogo.ROLES.values():
            self.assertTrue(
                datos_rol["permite_alcance_global"]
                or datos_rol["permite_alcance_empresa"]
                or datos_rol["permite_alcance_sucursal"]
            )
