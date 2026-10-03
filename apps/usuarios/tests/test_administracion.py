import uuid
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.usuarios.models import Rol, RolUsuario, Usuario
from apps.usuarios.serializadores import (
    SerializadorAsignacionRol,
    SerializadorCreacionUsuario,
    SerializadorRestablecimientoContrasena,
)
from apps.usuarios.servicios.administracion import (
    _puede_asignar_rol,
    _rol_es_compatible_con_modo,
    actualizar_usuario_administrado,
    revocar_rol_usuario,
)
from apps.usuarios.vistas import (
    VistaDetalleActualizacionUsuario,
    VistaListaCreacionUsuarios,
    VistaRestablecimientoContrasena,
    VistaRevocacionRolUsuario,
    VistaRolesAsignables,
    VistaRolesUsuario,
)


@override_settings(
    MODO_APLICACION="EXTERNO",
    PROVEEDOR_AUTENTICACION="LOCAL",
)
class PruebasAPIAdministracionUsuarios(SimpleTestCase):
    def setUp(self):
        self.fabrica = APIRequestFactory()
        self.administrador = Usuario(
            id=uuid.uuid4(),
            correo="administrador@empresa.test",
            nombres="Ana",
            apellidos="Administradora",
        )

    def _datos_usuario(self):
        return {
            "correo": "nuevo@empresa.test",
            "nombres": "Nuevo",
            "apellidos": "Usuario",
            "contrasena_temporal": "ClaveTemporal-2026!",
            "rol_codigo": "SOLICITANTE_EXTERNO",
            "tipo_alcance": "EMPRESA",
            "empresa_id": str(uuid.uuid4()),
        }

    def test_creacion_requiere_autenticacion(self):
        respuesta = self.client.post(
            reverse("usuarios:lista-creacion"),
            self._datos_usuario(),
        )

        self.assertEqual(respuesta.status_code, 401)

    @patch("apps.usuarios.vistas.SerializadorUsuarioAdministrado")
    @patch("apps.usuarios.vistas.crear_usuario_administrado")
    def test_creacion_delega_en_servicio_y_no_expone_contrasena(
        self,
        crear_usuario,
        serializador_salida,
    ):
        creado = MagicMock()
        crear_usuario.return_value = creado
        serializador_salida.return_value.data = {
            "id": str(uuid.uuid4()),
            "correo": "nuevo@empresa.test",
        }
        solicitud = self.fabrica.post(
            reverse("usuarios:lista-creacion"),
            self._datos_usuario(),
            format="json",
        )
        force_authenticate(solicitud, user=self.administrador)

        respuesta = VistaListaCreacionUsuarios.as_view()(solicitud)

        self.assertEqual(respuesta.status_code, 201)
        self.assertNotIn("contrasena_temporal", respuesta.data)
        crear_usuario.assert_called_once()

    @patch("apps.usuarios.vistas.crear_usuario_administrado")
    def test_servicio_impide_creacion_sin_permisos(self, crear_usuario):
        crear_usuario.side_effect = PermissionDenied(
            'No tiene el permiso requerido: "usuario.administrar".'
        )
        solicitud = self.fabrica.post(
            reverse("usuarios:lista-creacion"),
            self._datos_usuario(),
            format="json",
        )
        force_authenticate(solicitud, user=self.administrador)

        respuesta = VistaListaCreacionUsuarios.as_view()(solicitud)

        self.assertEqual(respuesta.status_code, 403)

    @patch("apps.usuarios.vistas.SerializadorRolAsignable")
    @patch("apps.usuarios.vistas.listar_roles_asignables")
    def test_roles_asignables_dependen_del_alcance(
        self,
        listar_roles,
        serializador_salida,
    ):
        listar_roles.return_value = []
        serializador_salida.return_value.data = []
        empresa_id = uuid.uuid4()
        solicitud = self.fabrica.get(
            reverse("usuarios:roles-asignables"),
            {"tipo_alcance": "EMPRESA", "empresa_id": str(empresa_id)},
        )
        force_authenticate(solicitud, user=self.administrador)

        respuesta = VistaRolesAsignables.as_view()(solicitud)

        self.assertEqual(respuesta.status_code, 200)
        listar_roles.assert_called_once_with(
            self.administrador,
            tipo_alcance="EMPRESA",
            empresa_id=empresa_id,
        )

    def test_contrasena_local_es_obligatoria(self):
        datos = self._datos_usuario()
        datos.pop("contrasena_temporal")

        serializador = SerializadorCreacionUsuario(data=datos)

        self.assertFalse(serializador.is_valid())
        self.assertIn("contrasena_temporal", serializador.errors)

    def test_un_rol_corporativo_no_es_compatible_con_network(self):
        rol = Rol(codigo="SOLICITANTE_CORPORATIVO", nombre="Solicitante")

        self.assertFalse(_rol_es_compatible_con_modo(rol))

    @override_settings(MODO_APLICACION="CORPORATIVO")
    def test_administrador_corporativo_puede_delegar_rol_de_repartidor(self):
        rol = Rol(
            codigo="REPARTIDOR_CORPORATIVO",
            nombre="Repartidor corporativo",
            permite_alcance_empresa=True,
        )

        resultado = _puede_asignar_rol(
            self.administrador,
            rol,
            "EMPRESA",
            MagicMock(),
            None,
            {"ADMINISTRADOR_CORPORATIVO"},
        )

        self.assertTrue(resultado)

    @patch("apps.usuarios.vistas.SerializadorUsuarioAdministrado")
    @patch("apps.usuarios.vistas.obtener_usuario_autorizado")
    def test_detalle_usa_selector_autorizado(
        self,
        obtener_usuario,
        serializador_salida,
    ):
        objetivo = MagicMock()
        obtener_usuario.return_value = objetivo
        serializador_salida.return_value.data = {
            "id": str(uuid.uuid4()),
            "correo": "usuario@empresa.test",
        }
        usuario_id = uuid.uuid4()
        solicitud = self.fabrica.get(
            reverse(
                "usuarios:detalle-actualizacion",
                kwargs={"usuario_id": usuario_id},
            )
        )
        force_authenticate(solicitud, user=self.administrador)

        respuesta = VistaDetalleActualizacionUsuario.as_view()(
            solicitud,
            usuario_id=usuario_id,
        )

        self.assertEqual(respuesta.status_code, 200)
        obtener_usuario.assert_called_once_with(self.administrador, usuario_id)

    @patch("apps.usuarios.vistas.SerializadorUsuarioAdministrado")
    @patch("apps.usuarios.vistas.actualizar_usuario_administrado")
    @patch("apps.usuarios.vistas.obtener_usuario_autorizado")
    def test_actualizacion_exige_permiso_administrativo(
        self,
        obtener_usuario,
        actualizar_usuario,
        serializador_salida,
    ):
        objetivo = MagicMock()
        obtener_usuario.return_value = objetivo
        actualizar_usuario.return_value = objetivo
        serializador_salida.return_value.data = {"estado": "SUSPENDIDO"}
        usuario_id = uuid.uuid4()
        solicitud = self.fabrica.patch(
            reverse(
                "usuarios:detalle-actualizacion",
                kwargs={"usuario_id": usuario_id},
            ),
            {"estado": "SUSPENDIDO"},
            format="json",
        )
        force_authenticate(solicitud, user=self.administrador)

        respuesta = VistaDetalleActualizacionUsuario.as_view()(
            solicitud,
            usuario_id=usuario_id,
        )

        self.assertEqual(respuesta.status_code, 200)
        obtener_usuario.assert_called_once_with(
            self.administrador,
            usuario_id,
            codigo_permiso="usuario.administrar",
        )
        actualizar_usuario.assert_called_once()

    @patch("apps.usuarios.vistas.restablecer_contrasena_usuario")
    @patch("apps.usuarios.vistas.obtener_usuario_autorizado")
    def test_restablecimiento_local_responde_204(
        self,
        obtener_usuario,
        restablecer,
    ):
        objetivo = Usuario(
            id=uuid.uuid4(),
            correo="objetivo@empresa.test",
            nombres="Usuario",
            apellidos="Objetivo",
        )
        obtener_usuario.return_value = objetivo
        solicitud = self.fabrica.post(
            reverse(
                "usuarios:restablecer-contrasena",
                kwargs={"usuario_id": objetivo.id},
            ),
            {"contrasena_temporal": "Nueva-Clave-Temporal-2026!"},
            format="json",
        )
        force_authenticate(solicitud, user=self.administrador)

        respuesta = VistaRestablecimientoContrasena.as_view()(
            solicitud,
            usuario_id=objetivo.id,
        )

        self.assertEqual(respuesta.status_code, 204)
        restablecer.assert_called_once_with(
            self.administrador,
            objetivo,
            "Nueva-Clave-Temporal-2026!",
        )

    @patch(
        "apps.usuarios.servicios.administracion._exigir_administracion_usuario"
    )
    @patch("apps.usuarios.servicios.administracion.Usuario.objetos.select_for_update")
    def test_administrador_no_puede_desactivarse_a_si_mismo(
        self,
        seleccionar,
        exigir_administracion,
    ):
        seleccionar.return_value.get.return_value = self.administrador

        with self.assertRaises(ValidationError):
            actualizar_usuario_administrado.__wrapped__(
                self.administrador,
                self.administrador,
                {"estado": "INACTIVO"},
            )

        exigir_administracion.assert_called_once()

    def test_valida_fortaleza_de_contrasena_temporal(self):
        objetivo = Usuario(
            correo="objetivo@empresa.test",
            nombres="Usuario",
            apellidos="Objetivo",
        )
        serializador = SerializadorRestablecimientoContrasena(
            data={"contrasena_temporal": "123"},
            context={"usuario_objetivo": objetivo},
        )

        self.assertFalse(serializador.is_valid())
        self.assertIn("contrasena_temporal", serializador.errors)

    def test_normaliza_codigo_al_asignar_rol(self):
        serializador = SerializadorAsignacionRol(
            data={
                "rol_codigo": " solicitante_externo ",
                "tipo_alcance": "GLOBAL",
            }
        )

        self.assertTrue(serializador.is_valid(), serializador.errors)
        self.assertEqual(
            serializador.validated_data["rol_codigo"],
            "SOLICITANTE_EXTERNO",
        )

    @patch("apps.usuarios.vistas.SerializadorAsignacionRolUsuario")
    @patch(
        "apps.usuarios.vistas.listar_asignaciones_roles_usuario_autorizadas"
    )
    def test_consulta_historial_de_roles_autorizado(
        self,
        listar_asignaciones,
        serializador_salida,
    ):
        usuario_id = uuid.uuid4()
        asignaciones = MagicMock()
        listar_asignaciones.return_value = asignaciones
        serializador_salida.return_value.data = []
        solicitud = self.fabrica.get(
            reverse(
                "usuarios:roles-usuario",
                kwargs={"usuario_id": usuario_id},
            )
        )
        force_authenticate(solicitud, user=self.administrador)

        respuesta = VistaRolesUsuario.as_view()(
            solicitud,
            usuario_id=usuario_id,
        )

        self.assertEqual(respuesta.status_code, 200)
        listar_asignaciones.assert_called_once_with(
            self.administrador,
            usuario_id,
        )
        serializador_salida.assert_called_once_with(
            asignaciones,
            many=True,
        )

    @patch("apps.usuarios.vistas.SerializadorAsignacionRolUsuario")
    @patch("apps.usuarios.vistas.asignar_rol_usuario")
    @patch("apps.usuarios.vistas.obtener_usuario_autorizado")
    def test_asignacion_de_rol_responde_201(
        self,
        obtener_usuario,
        asignar_rol,
        serializador_salida,
    ):
        usuario_id = uuid.uuid4()
        objetivo = MagicMock()
        asignacion = MagicMock()
        obtener_usuario.return_value = objetivo
        asignar_rol.return_value = asignacion
        serializador_salida.return_value.data = {"id": str(uuid.uuid4())}
        solicitud = self.fabrica.post(
            reverse(
                "usuarios:roles-usuario",
                kwargs={"usuario_id": usuario_id},
            ),
            {
                "rol_codigo": "SOLICITANTE_EXTERNO",
                "tipo_alcance": "GLOBAL",
            },
            format="json",
        )
        force_authenticate(solicitud, user=self.administrador)

        respuesta = VistaRolesUsuario.as_view()(
            solicitud,
            usuario_id=usuario_id,
        )

        self.assertEqual(respuesta.status_code, 201)
        obtener_usuario.assert_called_once_with(
            self.administrador,
            usuario_id,
            codigo_permiso="usuario.administrar",
        )
        asignar_rol.assert_called_once()

    @patch("apps.usuarios.vistas.revocar_rol_usuario")
    @patch("apps.usuarios.vistas.obtener_usuario_autorizado")
    def test_revocacion_de_rol_responde_204(
        self,
        obtener_usuario,
        revocar_rol,
    ):
        usuario_id = uuid.uuid4()
        asignacion_id = uuid.uuid4()
        objetivo = MagicMock()
        obtener_usuario.return_value = objetivo
        solicitud = self.fabrica.delete(
            reverse(
                "usuarios:revocar-rol-usuario",
                kwargs={
                    "usuario_id": usuario_id,
                    "asignacion_id": asignacion_id,
                },
            )
        )
        force_authenticate(solicitud, user=self.administrador)

        respuesta = VistaRevocacionRolUsuario.as_view()(
            solicitud,
            usuario_id=usuario_id,
            asignacion_id=asignacion_id,
        )

        self.assertEqual(respuesta.status_code, 204)
        revocar_rol.assert_called_once_with(
            self.administrador,
            objetivo,
            asignacion_id,
        )

    @patch("apps.usuarios.servicios.administracion.cerrar_todas_las_sesiones")
    @patch("apps.usuarios.servicios.administracion._rol_es_administrativo")
    @patch("apps.usuarios.servicios.administracion._puede_asignar_rol")
    @patch("apps.usuarios.servicios.administracion._exigir_administracion")
    @patch(
        "apps.usuarios.servicios.administracion._exigir_administracion_usuario"
    )
    @patch("apps.usuarios.servicios.administracion.RolUsuario.objetos.select_for_update")
    @patch("apps.usuarios.servicios.administracion.Usuario.objetos.select_for_update")
    def test_revocacion_conserva_historial_y_cierra_sesiones(
        self,
        seleccionar_usuario,
        seleccionar_asignacion,
        exigir_usuario,
        exigir_alcance,
        puede_asignar,
        rol_es_administrativo,
        cerrar_sesiones,
    ):
        objetivo = Usuario(
            id=uuid.uuid4(),
            correo="objetivo@empresa.test",
            nombres="Usuario",
            apellidos="Objetivo",
        )
        asignacion = MagicMock(spec=RolUsuario)
        asignacion.pk = uuid.uuid4()
        asignacion.rol = MagicMock()
        asignacion.tipo_alcance = "EMPRESA"
        asignacion.empresa = MagicMock()
        asignacion.sucursal = None
        seleccionar_usuario.return_value.get.return_value = objetivo
        (
            seleccionar_asignacion.return_value.select_related.return_value
            .get.return_value
        ) = asignacion
        puede_asignar.return_value = True
        rol_es_administrativo.return_value = False

        resultado = revocar_rol_usuario.__wrapped__(
            self.administrador,
            objetivo,
            asignacion.pk,
        )

        self.assertIs(resultado, asignacion)
        self.assertFalse(asignacion.activo)
        self.assertEqual(asignacion.revocado_por, self.administrador)
        self.assertIsNotNone(asignacion.revocado_en)
        asignacion.save.assert_called_once()
        cerrar_sesiones.assert_called_once_with(objetivo)
        exigir_usuario.assert_called_once()
        exigir_alcance.assert_called_once()

    @patch(
        "apps.usuarios.servicios.administracion._bloquear_revocaciones_administrativas"
    )
    @patch("apps.usuarios.servicios.administracion._existe_otro_administrador")
    @patch("apps.usuarios.servicios.administracion._rol_es_administrativo")
    @patch("apps.usuarios.servicios.administracion._puede_asignar_rol")
    @patch("apps.usuarios.servicios.administracion._exigir_administracion")
    @patch(
        "apps.usuarios.servicios.administracion._exigir_administracion_usuario"
    )
    @patch("apps.usuarios.servicios.administracion.RolUsuario.objetos.select_for_update")
    @patch("apps.usuarios.servicios.administracion.Usuario.objetos.select_for_update")
    def test_no_puede_revocar_su_ultimo_rol_administrativo(
        self,
        seleccionar_usuario,
        seleccionar_asignacion,
        exigir_usuario,
        exigir_alcance,
        puede_asignar,
        rol_es_administrativo,
        existe_otro_administrador,
        bloquear_revocaciones,
    ):
        asignacion = MagicMock(spec=RolUsuario)
        asignacion.pk = uuid.uuid4()
        asignacion.rol = MagicMock()
        asignacion.tipo_alcance = "EMPRESA"
        asignacion.empresa = MagicMock()
        asignacion.sucursal = None
        seleccionar_usuario.return_value.get.return_value = self.administrador
        (
            seleccionar_asignacion.return_value.select_related.return_value
            .get.return_value
        ) = asignacion
        puede_asignar.return_value = True
        rol_es_administrativo.return_value = True
        existe_otro_administrador.return_value = False

        with self.assertRaises(ValidationError):
            revocar_rol_usuario.__wrapped__(
                self.administrador,
                self.administrador,
                asignacion.pk,
            )

        existe_otro_administrador.assert_called_once_with(
            asignacion,
            usuario_id=self.administrador.pk,
        )
        bloquear_revocaciones.assert_called_once_with()
        asignacion.save.assert_not_called()


@override_settings(
    MODO_APLICACION="CORPORATIVO",
    PROVEEDOR_AUTENTICACION="JWT_CORPORATIVO",
)
class PruebasContratoUsuarioCorporativo(SimpleTestCase):
    def test_rechaza_contrasena_local(self):
        serializador = SerializadorCreacionUsuario(
            data={
                "correo": "corporativo@analiza.test",
                "nombres": "Usuario",
                "apellidos": "Corporativo",
                "contrasena_temporal": "ClaveTemporal-2026!",
                "rol_codigo": "SOLICITANTE_CORPORATIVO",
                "tipo_alcance": "GLOBAL",
            }
        )

        self.assertFalse(serializador.is_valid())
        self.assertIn("contrasena_temporal", serializador.errors)

    @patch("apps.usuarios.vistas.obtener_usuario_autorizado")
    def test_endpoint_de_restablecimiento_no_existe_con_jwt_corporativo(
        self,
        obtener_usuario,
    ):
        usuario = Usuario(
            id=uuid.uuid4(),
            correo="administrador@analiza.test",
            nombres="Administrador",
            apellidos="Corporativo",
        )
        solicitud = APIRequestFactory().post(
            reverse(
                "usuarios:restablecer-contrasena",
                kwargs={"usuario_id": uuid.uuid4()},
            ),
            {"contrasena_temporal": "Nueva-Clave-2026!"},
            format="json",
        )
        force_authenticate(solicitud, user=usuario)

        respuesta = VistaRestablecimientoContrasena.as_view()(
            solicitud,
            usuario_id=uuid.uuid4(),
        )

        self.assertEqual(respuesta.status_code, 404)
        obtener_usuario.assert_not_called()
