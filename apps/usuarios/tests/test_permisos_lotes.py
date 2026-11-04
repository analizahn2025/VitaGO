"""Autorización agrupada: consultas acotadas y revocación inmediata."""

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.organizaciones.models import Sucursal
from apps.repartidores.tests import test_resumenes as datos
from apps.usuarios.models import Permiso, PermisoRol, Rol, RolUsuario
from apps.usuarios.servicios import obtener_alcances_permisos


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasPermisosEnLote(TestCase):
    setUpTestData = classmethod(datos.PruebasResumenesMotoristas.setUpTestData.__func__)
    _lector = datos.PruebasResumenesMotoristas._lector

    def test_varios_permisos_normalizados_en_una_sola_consulta(self):
        usuario = self._lector()
        with self.assertNumQueries(1):
            alcances = obtener_alcances_permisos(usuario, (
                " REPORTE.VER ", "solicitud.ver", "jornada.ver", "evidencia.ver", "reporte.ver", "permiso.inexistente",
            ))
        self.assertEqual(len(alcances), 5)
        for codigo in ("reporte.ver", "solicitud.ver", "jornada.ver", "evidencia.ver"):
            self.assertFalse(alcances[codigo].global_)
            self.assertEqual(alcances[codigo].empresas, frozenset({self.empresa.pk}))
        self.assertFalse(alcances["permiso.inexistente"].tiene_algun_alcance)

    def test_alcance_global_de_un_permiso_no_se_extiende_a_otro(self):
        usuario = self._lector(permisos=("solicitud.ver",))
        rol = Rol.objetos.create(codigo="GLOBAL_LOTE", nombre="Global de prueba", permite_alcance_global=True)
        PermisoRol.objetos.create(rol=rol, permiso=Permiso.objetos.get(codigo="reporte.ver"))
        RolUsuario.objetos.create(usuario=usuario, rol=rol, tipo_alcance="GLOBAL")
        with self.assertNumQueries(1):
            alcances = obtener_alcances_permisos(usuario, ("reporte.ver", "solicitud.ver", "evidencia.ver"))
        self.assertTrue(alcances["reporte.ver"].global_)
        self.assertFalse(alcances["solicitud.ver"].global_)
        self.assertEqual(alcances["solicitud.ver"].empresas, frozenset({self.empresa.pk}))
        self.assertFalse(alcances["evidencia.ver"].tiene_algun_alcance)

    def test_revocar_rol_se_refleja_en_la_siguiente_lectura(self):
        usuario = self._lector()
        self.assertTrue(obtener_alcances_permisos(usuario, ("reporte.ver",))["reporte.ver"].tiene_algun_alcance)
        RolUsuario.objetos.filter(usuario=usuario).update(activo=False, revocado_en=timezone.now(), revocado_por=self.administrador)
        with self.assertNumQueries(1):
            self.assertFalse(obtener_alcances_permisos(usuario, ("reporte.ver",))["reporte.ver"].tiene_algun_alcance)

    def test_anonimo_inactivo_superusuario_y_lote_vacio_no_consultan(self):
        usuario = self._lector()
        usuario.estado = "INACTIVO"
        with self.assertNumQueries(0):
            for actor in (None, AnonymousUser(), usuario):
                self.assertFalse(obtener_alcances_permisos(actor, ("reporte.ver",))["reporte.ver"].tiene_algun_alcance)
            self.assertEqual(obtener_alcances_permisos(usuario, ()), {})
            self.assertTrue(obtener_alcances_permisos(self.administrador, ("reporte.ver",))["reporte.ver"].global_)

    def test_alcance_sucursal_no_habilita_empresa_completa(self):
        sucursal = Sucursal.objects.create(empresa=self.empresa, ubicacion=self.origen, nombre="Sucursal del lote")
        usuario = self._lector(sucursal=sucursal)
        with self.assertNumQueries(1):
            alcances = obtener_alcances_permisos(usuario, ("reporte.ver", "solicitud.ver"))
        for alcance in alcances.values():
            self.assertFalse(alcance.global_)
            self.assertEqual(alcance.empresas, frozenset())
            self.assertEqual(alcance.sucursales, frozenset({sucursal.pk}))
            self.assertEqual(alcance.empresas_visibles, frozenset({self.empresa.pk}))
