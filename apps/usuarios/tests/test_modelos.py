from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings

from apps.geografia.models import Pais
from apps.organizaciones.models import Empresa, Sucursal
from apps.ubicaciones.opciones import OrigenUbicacion
from apps.ubicaciones.models import TipoUbicacion, Ubicacion
from apps.usuarios.opciones import EstadoUsuario
from apps.usuarios.models import Usuario


class PruebasModeloUsuario(SimpleTestCase):
    def test_usuario_esta_activo_cuando_estado_es_activo(self):
        usuario = Usuario(
            correo="usuario@example.com",
            nombres="Usuario",
            apellidos="Prueba",
        )

        self.assertEqual(usuario.estado, EstadoUsuario.ACTIVO)
        self.assertTrue(usuario.is_active)

    @override_settings(MODO_APLICACION="CORPORATIVO")
    def test_usuario_corporativo_rechaza_contrasena_local_utilizable(self):
        usuario = Usuario(
            correo="corporativo@example.com",
            nombres="Usuario",
            apellidos="Corporativo",
        )
        usuario.set_password("contrasena-local")

        with self.assertRaises(ValidationError):
            usuario.clean()

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_usuario_externo_acepta_contrasena_local_con_hash(self):
        usuario = Usuario(
            correo="externo@example.com",
            nombres="Usuario",
            apellidos="Externo",
        )
        usuario.set_password("contrasena-local")

        usuario.clean()

        self.assertTrue(usuario.check_password("contrasena-local"))

    def test_sucursal_debe_pertenecer_a_empresa_del_usuario(self):
        pais = Pais(
            iso2="HN",
            iso3="HND",
            nombre="Honduras",
            codigo_telefonico="+504",
            codigo_moneda="HNL",
            zona_horaria_predeterminada="America/Tegucigalpa",
        )
        empresa_elegida = Empresa(nombre="Elegida", pais=pais)
        empresa_sucursal = Empresa(nombre="Dueña de sucursal", pais=pais)
        tipo_ubicacion = TipoUbicacion(codigo="SUCURSAL", nombre="Sucursal")
        ubicacion = Ubicacion(
            nombre="Sucursal principal",
            tipo_ubicacion=tipo_ubicacion,
            origen=OrigenUbicacion.REGISTRADA_USUARIO,
            pais=pais,
            direccion="Dirección de prueba",
            latitud=14.0723,
            longitud=-87.1921,
        )
        sucursal = Sucursal(
            empresa=empresa_sucursal,
            nombre="Principal",
            ubicacion=ubicacion,
        )
        usuario = Usuario(
            correo="usuario@example.com",
            nombres="Usuario",
            apellidos="Prueba",
            empresa=empresa_elegida,
            sucursal=sucursal,
        )

        with self.assertRaises(ValidationError):
            usuario.clean()

    def test_usuario_con_sucursal_requiere_empresa(self):
        pais = Pais(
            iso2="HN",
            iso3="HND",
            nombre="Honduras",
            codigo_telefonico="+504",
            codigo_moneda="HNL",
            zona_horaria_predeterminada="America/Tegucigalpa",
        )
        empresa_sucursal = Empresa(nombre="Dueña de sucursal", pais=pais)
        tipo_ubicacion = TipoUbicacion(codigo="SUCURSAL", nombre="Sucursal")
        ubicacion = Ubicacion(
            nombre="Sucursal principal",
            tipo_ubicacion=tipo_ubicacion,
            origen=OrigenUbicacion.REGISTRADA_USUARIO,
            pais=pais,
            direccion="Dirección de prueba",
            latitud=14.0723,
            longitud=-87.1921,
        )
        sucursal = Sucursal(
            empresa=empresa_sucursal,
            nombre="Principal",
            ubicacion=ubicacion,
        )
        usuario = Usuario(
            correo="usuario@example.com",
            nombres="Usuario",
            apellidos="Prueba",
            sucursal=sucursal,
        )

        with self.assertRaises(ValidationError):
            usuario.clean()
