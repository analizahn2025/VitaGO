"""Ningún administrador de empresa puede apropiarse de cuentas de plataforma."""

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from apps.usuarios.models import Rol, RolUsuario, Usuario
from apps.usuarios.opciones import TipoAlcanceRol
from apps.usuarios.servicios.administracion import (
    actualizar_usuario_administrado,
    asignar_rol_usuario,
    restablecer_contrasena_usuario,
    revocar_rol_usuario,
)
from apps.usuarios.tests import test_unificacion_roles as pruebas_base


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasProteccionSuperadministradores(TestCase):
    setUp = pruebas_base.PruebasUnificacionGerenciaOperativa.setUp
    _crear_usuario_con_rol = pruebas_base.PruebasUnificacionGerenciaOperativa._crear_usuario_con_rol

    def _administrador_empresa(self, codigo="ADMINISTRADOR_CORPORATIVO"):
        return self._crear_usuario_con_rol("administrador.empresa@analiza.test", codigo)

    def test_admin_empresa_no_cambia_contrasena_de_superusuario(self):
        administrador = self._administrador_empresa()
        anterior = self.administrador.password
        with self.assertRaises(PermissionDenied):
            restablecer_contrasena_usuario(administrador, self.administrador, "Clave-temporal-segura-2026!")
        self.administrador.refresh_from_db()
        self.assertEqual(self.administrador.password, anterior)

    def test_api_restablecimiento_superusuario_devuelve_403(self):
        cliente = APIClient()
        cliente.force_authenticate(self._administrador_empresa())
        respuesta = cliente.post(
            reverse("usuarios:restablecer-contrasena", kwargs={"usuario_id": self.administrador.id}),
            {"contrasena_temporal": "Clave-temporal-segura-2026!"}, format="json",
        )
        self.assertEqual(respuesta.status_code, 403)

    def test_admin_empresa_no_modifica_perfil_de_superusuario(self):
        with self.assertRaises(PermissionDenied):
            actualizar_usuario_administrado(self._administrador_empresa(), self.administrador, {"telefono": "12345678"})

    def test_rol_superadministrador_tambien_protege_sin_bandera_superusuario(self):
        objetivo = Usuario.objetos.create(
            correo="superadministrador.rol@analiza.test", nombres="Cuenta", apellidos="Plataforma", empresa=self.empresa,
        )
        asignacion = RolUsuario.objetos.create(
            usuario=objetivo, rol=Rol.objetos.get(codigo="SUPERADMINISTRADOR"),
            tipo_alcance=TipoAlcanceRol.GLOBAL, asignado_por=self.administrador,
        )
        administrador = self._administrador_empresa()
        with self.assertRaises(PermissionDenied):
            restablecer_contrasena_usuario(administrador, objetivo, "Clave-temporal-segura-2026!")
        with self.assertRaises(PermissionDenied):
            revocar_rol_usuario(administrador, objetivo, asignacion.id)
        with self.assertRaises(PermissionDenied):
            asignar_rol_usuario(administrador, objetivo, {
                "rol_codigo": "SOLICITANTE_CORPORATIVO", "tipo_alcance": TipoAlcanceRol.EMPRESA,
                "empresa_id": self.empresa.id,
            })

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_admin_empresa_network_no_administra_superusuario(self):
        administrador = self._administrador_empresa("ADMINISTRADOR_EMPRESA_EXTERNA")
        with self.assertRaises(PermissionDenied):
            restablecer_contrasena_usuario(administrador, self.administrador, "Clave-temporal-segura-2026!")

    def test_superusuario_conserva_administracion(self):
        actualizado = actualizar_usuario_administrado(self.administrador, self.administrador, {"telefono": "12345678"})
        self.assertEqual(actualizado.telefono, "12345678")

    def test_superadministrador_por_rol_conserva_administracion(self):
        actor = Usuario.objetos.create(correo="plataforma.actor@analiza.test", nombres="Actor", apellidos="Plataforma")
        RolUsuario.objetos.create(
            usuario=actor, rol=Rol.objetos.get(codigo="SUPERADMINISTRADOR"),
            tipo_alcance=TipoAlcanceRol.GLOBAL, asignado_por=self.administrador,
        )
        actualizado = actualizar_usuario_administrado(actor, self.administrador, {"telefono": "12345678"})
        self.assertEqual(actualizado.telefono, "12345678")

    def test_administrador_empresa_conserva_administracion_de_usuarios_operativos(self):
        administrador = self._administrador_empresa()
        objetivo = self._crear_usuario_con_rol("operativo.protegido@analiza.test", "SOLICITANTE_CORPORATIVO")
        actualizado = actualizar_usuario_administrado(administrador, objetivo, {"telefono": "12345678"})
        self.assertEqual(actualizado.telefono, "12345678")
