from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.utils import timezone

from apps.geografia.models import Pais
from apps.organizaciones.models import Empresa, Sucursal
from apps.ubicaciones.models import TipoUbicacion, Ubicacion
from apps.ubicaciones.opciones import OrigenUbicacion
from apps.usuarios.models import Permiso, Rol, RolUsuario, Usuario
from apps.usuarios.opciones import EstadoUsuario, TipoAlcanceRol
from apps.usuarios.servicios import usuario_tiene_permiso


class PruebasRolesYPermisos(SimpleTestCase):
    def setUp(self):
        self.pais = Pais(
            iso2="HN",
            iso3="HND",
            nombre="Honduras",
            codigo_telefonico="+504",
            codigo_moneda="HNL",
            zona_horaria_predeterminada="America/Tegucigalpa",
        )
        self.empresa = Empresa(nombre="Empresa", pais=self.pais)
        self.otra_empresa = Empresa(nombre="Otra empresa", pais=self.pais)
        tipo_ubicacion = TipoUbicacion(codigo="SUCURSAL", nombre="Sucursal")
        ubicacion = Ubicacion(
            nombre="Sucursal principal",
            tipo_ubicacion=tipo_ubicacion,
            origen=OrigenUbicacion.REGISTRADA_USUARIO,
            pais=self.pais,
            direccion="Dirección de prueba",
            latitud=14.0723,
            longitud=-87.1921,
        )
        self.sucursal = Sucursal(
            empresa=self.empresa,
            nombre="Principal",
            ubicacion=ubicacion,
        )
        self.usuario = Usuario(
            correo="usuario@example.com",
            nombres="Usuario",
            apellidos="Prueba",
        )
        self.rol = Rol(
            codigo="OPERADOR_RED",
            nombre="Operador de red",
            permite_alcance_global=True,
            permite_alcance_empresa=True,
            permite_alcance_sucursal=True,
        )

    def test_normaliza_codigos_de_rol_y_permiso(self):
        rol = Rol(
            codigo=" administrador_empresa ",
            nombre="Administrador",
            permite_alcance_empresa=True,
        )
        permiso = Permiso(codigo=" Solicitud.Crear ", nombre="Crear solicitud")

        rol.clean()
        permiso.clean()

        self.assertEqual(rol.codigo, "ADMINISTRADOR_EMPRESA")
        self.assertEqual(permiso.codigo, "solicitud.crear")

    def test_rol_requiere_al_menos_un_alcance_permitido(self):
        rol = Rol(codigo="SIN_ALCANCE", nombre="Sin alcance")

        with self.assertRaises(ValidationError):
            rol.clean()

    def test_asignacion_rechaza_alcance_no_permitido_por_rol(self):
        rol = Rol(
            codigo="SOLO_EMPRESA",
            nombre="Solo empresa",
            permite_alcance_empresa=True,
        )
        asignacion = RolUsuario(
            usuario=self.usuario,
            rol=rol,
            tipo_alcance=TipoAlcanceRol.GLOBAL,
        )

        with self.assertRaises(ValidationError):
            asignacion.clean()

    def test_alcance_global_rechaza_empresa(self):
        asignacion = RolUsuario(
            usuario=self.usuario,
            rol=self.rol,
            tipo_alcance=TipoAlcanceRol.GLOBAL,
            empresa=self.empresa,
        )

        with self.assertRaises(ValidationError):
            asignacion.clean()

    def test_alcance_empresa_requiere_empresa(self):
        asignacion = RolUsuario(
            usuario=self.usuario,
            rol=self.rol,
            tipo_alcance=TipoAlcanceRol.EMPRESA,
        )

        with self.assertRaises(ValidationError):
            asignacion.clean()

    def test_alcance_sucursal_requiere_sucursal_de_la_empresa(self):
        asignacion = RolUsuario(
            usuario=self.usuario,
            rol=self.rol,
            tipo_alcance=TipoAlcanceRol.SUCURSAL,
            empresa=self.otra_empresa,
            sucursal=self.sucursal,
        )

        with self.assertRaises(ValidationError):
            asignacion.clean()

    def test_asignacion_inactiva_requiere_fecha_de_revocacion(self):
        asignacion = RolUsuario(
            usuario=self.usuario,
            rol=self.rol,
            tipo_alcance=TipoAlcanceRol.GLOBAL,
            activo=False,
        )

        with self.assertRaises(ValidationError):
            asignacion.clean()

        asignacion.revocado_en = timezone.now()
        asignacion.clean()

    @patch("django.db.models.query.QuerySet.exists", return_value=True)
    def test_servicio_reconoce_permiso_activo_por_empresa(self, existe):
        resultado = usuario_tiene_permiso(
            self.usuario,
            " Solicitud.Crear ",
            empresa=self.empresa,
        )

        self.assertTrue(resultado)
        existe.assert_called_once()

    @patch("django.db.models.query.QuerySet.exists")
    def test_servicio_rechaza_usuario_inactivo_sin_consultar(self, existe):
        self.usuario.estado = EstadoUsuario.INACTIVO

        resultado = usuario_tiene_permiso(
            self.usuario,
            "solicitud.crear",
            empresa=self.empresa,
        )

        self.assertFalse(resultado)
        existe.assert_not_called()

    @patch("django.db.models.query.QuerySet.exists")
    def test_servicio_rechaza_contexto_de_sucursal_y_empresa_distintas(
        self,
        existe,
    ):
        resultado = usuario_tiene_permiso(
            self.usuario,
            "solicitud.crear",
            empresa=self.otra_empresa,
            sucursal=self.sucursal,
        )

        self.assertFalse(resultado)
        existe.assert_not_called()
