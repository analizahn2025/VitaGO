import uuid
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.organizaciones.models import Empresa, Sucursal
from apps.usuarios.models import Rol, RolUsuario, Usuario
from apps.usuarios.opciones import TipoAlcanceRol
from apps.usuarios.selectores import obtener_perfil_usuario
from apps.usuarios.vistas import VistaMiPerfil


class PruebasEndpointMiPerfil(SimpleTestCase):
    def test_requiere_autenticacion(self):
        respuesta = self.client.get(reverse("usuarios:mi-perfil"))

        self.assertEqual(respuesta.status_code, 401)
        self.assertEqual(respuesta["WWW-Authenticate"], "Bearer")

    @patch("apps.usuarios.vistas.obtener_perfil_usuario")
    def test_devuelve_contrato_del_perfil(self, obtener_perfil):
        identificador_usuario = uuid.uuid4()
        identificador_empresa = uuid.uuid4()
        usuario = Usuario(
            id=identificador_usuario,
            correo="usuario@example.com",
            nombres="Usuario",
            apellidos="Prueba",
        )
        obtener_perfil.return_value = {
            "usuario": {
                "id": identificador_usuario,
                "correo": usuario.correo,
                "nombres": usuario.nombres,
                "apellidos": usuario.apellidos,
                "telefono": None,
                "estado": "ACTIVO",
            },
            "empresa": {
                "id": identificador_empresa,
                "nombre": "Empresa de prueba",
            },
            "sucursal": None,
            "roles": [
                {
                    "codigo": "SOLICITANTE_EXTERNO",
                    "nombre": "Solicitante externo",
                    "tipo_alcance": "EMPRESA",
                    "empresa_id": identificador_empresa,
                    "sucursal_id": None,
                }
            ],
            "permisos": ["solicitud.crear", "solicitud.ver"],
        }
        solicitud = APIRequestFactory().get(reverse("usuarios:mi-perfil"))
        force_authenticate(solicitud, user=usuario)

        respuesta = VistaMiPerfil.as_view()(solicitud)

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            respuesta.data,
            {
                "usuario": {
                    "id": str(identificador_usuario),
                    "correo": "usuario@example.com",
                    "nombres": "Usuario",
                    "apellidos": "Prueba",
                    "telefono": None,
                    "estado": "ACTIVO",
                },
                "empresa": {
                    "id": str(identificador_empresa),
                    "nombre": "Empresa de prueba",
                },
                "sucursal": None,
                "roles": [
                    {
                        "codigo": "SOLICITANTE_EXTERNO",
                        "nombre": "Solicitante externo",
                        "tipo_alcance": "EMPRESA",
                        "empresa_id": str(identificador_empresa),
                        "sucursal_id": None,
                    }
                ],
                "permisos": ["solicitud.crear", "solicitud.ver"],
            },
        )
        obtener_perfil.assert_called_once_with(usuario)


class PruebasSelectorMiPerfil(SimpleTestCase):
    def setUp(self):
        self.empresa = Empresa(id=uuid.uuid4(), nombre="Empresa de prueba")
        self.sucursal = Sucursal(
            id=uuid.uuid4(),
            empresa=self.empresa,
            nombre="Sucursal principal",
        )
        self.usuario = Usuario(
            id=uuid.uuid4(),
            correo="usuario@example.com",
            nombres="Usuario",
            apellidos="Prueba",
            empresa=self.empresa,
            sucursal=self.sucursal,
        )
        self.rol = Rol(
            id=uuid.uuid4(),
            codigo="SOLICITANTE_EXTERNO",
            nombre="Solicitante externo",
            permite_alcance_empresa=True,
        )
        self.asignacion = RolUsuario(
            usuario=self.usuario,
            rol=self.rol,
            tipo_alcance=TipoAlcanceRol.EMPRESA,
            empresa=self.empresa,
        )

    @patch("apps.usuarios.selectores.Permiso.objetos.filter")
    @patch("apps.usuarios.selectores.RolUsuario.objetos.filter")
    def test_reune_roles_y_permisos_activos(
        self,
        filtrar_roles,
        filtrar_permisos,
    ):
        consulta_roles = MagicMock()
        consulta_roles.select_related.return_value.order_by.return_value = [
            self.asignacion
        ]
        filtrar_roles.return_value = consulta_roles
        consulta_permisos = MagicMock()
        consulta_permisos.distinct.return_value.order_by.return_value.values_list.return_value = [
            "solicitud.ver",
            "solicitud.crear",
            "solicitud.ver",
        ]
        filtrar_permisos.return_value = consulta_permisos

        perfil = obtener_perfil_usuario(self.usuario)

        self.assertEqual(
            perfil["permisos"],
            ["solicitud.crear", "solicitud.ver"],
        )
        self.assertEqual(
            perfil["roles"],
            [
                {
                    "codigo": "SOLICITANTE_EXTERNO",
                    "nombre": "Solicitante externo",
                    "tipo_alcance": TipoAlcanceRol.EMPRESA,
                    "empresa_id": self.empresa.id,
                    "sucursal_id": None,
                }
            ],
        )
        filtrar_roles.assert_called_once_with(
            usuario_id=self.usuario.pk,
            activo=True,
            rol__activo=True,
        )
        filtrar_permisos.assert_called_once_with(
            activo=True,
            asignaciones_roles__activo=True,
            asignaciones_roles__rol_id__in={self.rol.id},
        )

    @patch("apps.usuarios.selectores.Permiso.objetos.filter")
    @patch("apps.usuarios.selectores.RolUsuario.objetos.filter")
    def test_sin_roles_devuelve_autorizaciones_vacias(
        self,
        filtrar_roles,
        filtrar_permisos,
    ):
        consulta_roles = MagicMock()
        consulta_roles.select_related.return_value.order_by.return_value = []
        filtrar_roles.return_value = consulta_roles

        perfil = obtener_perfil_usuario(self.usuario)

        self.assertEqual(perfil["roles"], [])
        self.assertEqual(perfil["permisos"], [])
        filtrar_permisos.assert_not_called()

    @patch("apps.usuarios.selectores.Permiso.objetos.filter")
    @patch("apps.usuarios.selectores.RolUsuario.objetos.filter")
    def test_superusuario_recibe_catalogo_activo_completo(
        self,
        filtrar_roles,
        filtrar_permisos,
    ):
        self.usuario.es_superusuario = True
        consulta_roles = MagicMock()
        consulta_roles.select_related.return_value.order_by.return_value = []
        filtrar_roles.return_value = consulta_roles
        consulta_permisos = MagicMock()
        consulta_permisos.distinct.return_value.order_by.return_value.values_list.return_value = [
            "empresa.administrar",
            "solicitud.ver",
        ]
        filtrar_permisos.return_value = consulta_permisos

        perfil = obtener_perfil_usuario(self.usuario)

        self.assertEqual(
            perfil["permisos"],
            ["empresa.administrar", "solicitud.ver"],
        )
        filtrar_permisos.assert_called_once_with(activo=True)
