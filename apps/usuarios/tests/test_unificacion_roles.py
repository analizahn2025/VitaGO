from unittest.mock import MagicMock

from django.test import TestCase, override_settings
from rest_framework.exceptions import PermissionDenied

from apps.geografia.models import Pais
from apps.organizaciones.models import Empresa
from apps.usuarios.models import PermisoRol, Rol, RolUsuario, Usuario
from apps.usuarios.opciones import TipoAlcanceRol
from apps.usuarios.servicios.administracion import (
    _puede_asignar_rol,
    _rol_es_compatible_con_modo,
    actualizar_usuario_administrado,
)


@override_settings(
    MODO_APLICACION="CORPORATIVO",
    PROVEEDOR_AUTENTICACION="LOCAL",
)
class PruebasUnificacionGerenciaOperativa(TestCase):
    def setUp(self):
        self.pais = Pais.objects.create(
            iso2="HN",
            iso3="HND",
            nombre="Honduras",
            codigo_telefonico="+504",
            codigo_moneda="HNL",
            zona_horaria_predeterminada="America/Tegucigalpa",
        )
        self.empresa = Empresa.objects.create(nombre="Analiza", pais=self.pais)
        self.administrador = Usuario.objetos.create(
            correo="admin.unificacion@analiza.test",
            nombres="Admin",
            apellidos="Unificación",
            empresa=self.empresa,
            es_superusuario=True,
        )
        self.gerente_usuario = Usuario.objetos.create(
            correo="gerente.unificacion@analiza.test",
            nombres="Gerente",
            apellidos="Operaciones",
            empresa=self.empresa,
        )
        RolUsuario.objetos.create(
            usuario=self.gerente_usuario,
            rol=Rol.objetos.get(codigo="GERENTE_OPERACIONES"),
            tipo_alcance=TipoAlcanceRol.EMPRESA,
            empresa=self.empresa,
            asignado_por=self.administrador,
        )

    def _crear_usuario_con_rol(self, correo, codigo_rol):
        usuario = Usuario.objetos.create(
            correo=correo,
            nombres="Usuario",
            apellidos=codigo_rol,
            empresa=self.empresa,
        )
        RolUsuario.objetos.create(
            usuario=usuario,
            rol=Rol.objetos.get(codigo=codigo_rol),
            tipo_alcance=TipoAlcanceRol.EMPRESA,
            empresa=self.empresa,
            asignado_por=self.administrador,
        )
        return usuario

    def test_supervisor_corporativo_queda_inactivo(self):
        supervisor = Rol.objetos.get(codigo="SUPERVISOR_CORPORATIVO")

        self.assertFalse(supervisor.activo)
        self.assertFalse(_rol_es_compatible_con_modo(supervisor))

    def test_gerente_administra_usuarios_y_roles(self):
        permisos = set(
            PermisoRol.objetos.filter(
                rol__codigo="GERENTE_OPERACIONES",
                activo=True,
                permiso__activo=True,
            ).values_list("permiso__codigo", flat=True)
        )

        self.assertIn("usuario.administrar", permisos)
        self.assertIn("rol.asignar", permisos)
        self.assertIn("solicitud.crear_envio_especial", permisos)

    def test_gerente_delega_solicitantes_y_motoristas(self):
        empresa = MagicMock()
        for codigo in ("SOLICITANTE_CORPORATIVO", "REPARTIDOR_CORPORATIVO"):
            rol = Rol.objetos.get(codigo=codigo)
            self.assertTrue(
                _puede_asignar_rol(
                    self.gerente_usuario,
                    rol,
                    "EMPRESA",
                    empresa,
                    None,
                    {"GERENTE_OPERACIONES"},
                )
            )

    def test_gerente_no_puede_delegar_administradores_ni_gerentes(self):
        empresa = MagicMock()
        for codigo in ("ADMINISTRADOR_CORPORATIVO", "GERENTE_OPERACIONES"):
            rol = Rol.objetos.get(codigo=codigo)
            self.assertFalse(
                _puede_asignar_rol(
                    self.gerente_usuario,
                    rol,
                    "EMPRESA",
                    empresa,
                    None,
                    {"GERENTE_OPERACIONES"},
                )
            )

    def test_gerente_actualiza_usuario_operativo(self):
        solicitante = self._crear_usuario_con_rol(
            "solicitante.unificacion@analiza.test",
            "SOLICITANTE_CORPORATIVO",
        )

        actualizado = actualizar_usuario_administrado(
            self.gerente_usuario,
            solicitante,
            {"telefono": "+50499990000"},
        )

        self.assertEqual(actualizado.telefono, "+50499990000")

    def test_gerente_no_modifica_administradores_ni_otros_gerentes(self):
        administrador = self._crear_usuario_con_rol(
            "administrador.protegido@analiza.test",
            "ADMINISTRADOR_CORPORATIVO",
        )
        otro_gerente = self._crear_usuario_con_rol(
            "gerente.protegido@analiza.test",
            "GERENTE_OPERACIONES",
        )

        for usuario in (administrador, otro_gerente):
            with self.assertRaises(PermissionDenied):
                actualizar_usuario_administrado(
                    self.gerente_usuario,
                    usuario,
                    {"telefono": "+50499991111"},
                )
