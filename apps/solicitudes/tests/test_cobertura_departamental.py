"""Destinos Corporate por país/departamento, sin alterar ciudades ni distancias."""

from unicodedata import normalize
from unittest.mock import patch

from django.http import Http404
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.geografia.models import Pais
from apps.organizaciones.models import Empresa, Sucursal
from apps.solicitudes.excepciones import CreacionSolicitudNoDisponible
from apps.solicitudes.models import Solicitud
from apps.solicitudes.selectores import obtener_opciones_creacion_solicitud
from apps.solicitudes.servicios import crear_solicitud
from apps.solicitudes.tests import test_modalidades_corporativas as datos
from apps.ubicaciones.models import Ubicacion, UbicacionEmpresa
from apps.usuarios.models import Rol, RolUsuario


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasCoberturaDepartamental(TestCase):
    setUpTestData = classmethod(datos.PruebasModalidadesCorporativas.setUpTestData.__func__)
    _crear_ubicacion = classmethod(datos.PruebasModalidadesCorporativas._crear_ubicacion.__func__)
    _crear_usuario_con_rol = classmethod(datos.PruebasModalidadesCorporativas._crear_usuario_con_rol.__func__)
    _datos_creacion = datos.PruebasModalidadesCorporativas._datos_creacion

    def setUp(self):
        self.cliente = APIClient()
        self.cliente.force_authenticate(self.solicitante)
        self.enterContext(patch("apps.rutas.proveedor_google.urlopen", side_effect=AssertionError("Sin Google real.")))

    def _opciones(self, **cambios):
        respuesta = self.cliente.get(reverse("solicitudes:opciones-creacion"), {
            "empresa_id": str(self.empresa.pk), "modalidad": "ENTRE_SUCURSALES",
            "origen_id": str(self.origen.pk), **cambios,
        })
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        return respuesta.data

    def _comprobar_destino(self, permitido):
        destinos = {p["ubicacion"]["id"] for p in self._opciones()["destinos"]}
        self.assertEqual(str(self.destino.pk) in destinos, permitido)
        if permitido:
            solicitud = crear_solicitud(self.gerente, self._datos_creacion("ENTRE_SUCURSALES"))
            self.assertEqual(solicitud.destino_id, self.destino.pk)
        else:
            with self.assertRaises((ValidationError, Http404)):
                crear_solicitud(self.gerente, self._datos_creacion("ENTRE_SUCURSALES"))
            self.assertFalse(Solicitud.objects.exists())

    def test_tegucigalpa_comayaguela_permitidas_sin_renombrar_ciudad(self):
        Ubicacion.objects.filter(pk=self.destino.pk).update(localidad="Comayagüela", nivel_administrativo_2="Distrito Central")
        self._comprobar_destino(True)
        self.destino.refresh_from_db()
        self.assertEqual(self.destino.localidad, "Comayagüela")

    def test_municipios_distintos_del_mismo_departamento_permitidos(self):
        Ubicacion.objects.filter(pk=self.origen.pk).update(nivel_administrativo_2="Distrito Central")
        Ubicacion.objects.filter(pk=self.destino.pk).update(localidad="El Zamorano", nivel_administrativo_2="San Antonio de Oriente")
        self._comprobar_destino(True)

    def test_sps_choloma_y_la_lima_se_permiten_por_cortes(self):
        Ubicacion.objects.filter(pk=self.origen.pk).update(localidad="San Pedro Sula", nivel_administrativo_1="Cortés")
        for ciudad in ("Choloma", "La Lima"):
            with self.subTest(ciudad=ciudad):
                Ubicacion.objects.filter(pk=self.destino.pk).update(localidad=ciudad, nivel_administrativo_1="Cortés")
                self._comprobar_destino(True)

    def test_departamento_distinto_se_rechaza_aunque_ciudad_coincida(self):
        Ubicacion.objects.filter(pk=self.destino.pk).update(nivel_administrativo_1="Cortés")
        self._comprobar_destino(False)

    def test_pais_distinto_se_rechaza_aunque_departamento_coincida(self):
        pais = Pais.objects.create(iso2="ZZ", iso3="ZZZ", nombre="País sintético", codigo_telefonico="+999", codigo_moneda="ZZZ", zona_horaria_predeterminada="UTC")
        Ubicacion.objects.filter(pk=self.destino.pk).update(pais=pais)
        self._comprobar_destino(False)

    def test_falta_departamento_origen_devuelve_aviso_y_error_de_campo(self):
        for valor in (None, "", " \t "):
            with self.subTest(valor=valor):
                Ubicacion.objects.filter(pk=self.origen.pk).update(nivel_administrativo_1=valor)
                opciones = self._opciones()
                self.assertEqual(opciones["destinos"], [])
                self.assertIn("no tiene departamento", opciones["mensaje_disponibilidad"])
                with self.assertRaises(ValidationError) as error:
                    crear_solicitud(self.gerente, self._datos_creacion("ENTRE_SUCURSALES"))
                self.assertIn("origen_id", error.exception.detail)

    def test_falta_departamento_destino_no_autoriza_por_coincidir_ciudad(self):
        for valor in (None, "", " \t "):
            with self.subTest(valor=valor):
                Ubicacion.objects.filter(pk=self.destino.pk).update(nivel_administrativo_1=valor)
                self._comprobar_destino(False)

    def test_normalizacion_compartida_espacios_mayusculas_y_unicode(self):
        Ubicacion.objects.filter(pk=self.origen.pk).update(nivel_administrativo_1=" FRANCISCO   MORAZÁN ", localidad=None)
        Ubicacion.objects.filter(pk=self.destino.pk).update(nivel_administrativo_1=normalize("NFD", "francisco morazán"), localidad="Ciudad distinta")
        self._comprobar_destino(True)

    def test_no_hay_limite_de_distancia_adicional(self):
        # Coordenadas sintéticas muy separadas; no representan sucursales reales.
        Ubicacion.objects.filter(pk=self.origen.pk).update(latitud="0", longitud="0")
        Ubicacion.objects.filter(pk=self.destino.pk).update(latitud="60", longitud="90")
        self._comprobar_destino(True)

    def test_origen_y_destino_iguales_siguen_prohibidos(self):
        UbicacionEmpresa.objects.filter(empresa=self.empresa, ubicacion=self.origen).update(permite_destino=True)
        with self.assertRaises(ValidationError) as error:
            crear_solicitud(self.gerente, self._datos_creacion("ENTRE_SUCURSALES", destino_id=self.origen.pk))
        self.assertIn("destino_id", error.exception.detail)

    def test_sucursal_ajena_no_se_habilita_por_compartir_departamento(self):
        otra_empresa = Empresa.objects.create(nombre="Empresa ajena", pais=self.pais)
        Sucursal.objects.filter(ubicacion=self.destino).update(empresa=otra_empresa)
        self._comprobar_destino(False)

    def test_sucursal_inactiva_no_se_habilita_por_compartir_departamento(self):
        Sucursal.objects.filter(ubicacion=self.destino).update(estado="INACTIVO")
        self._comprobar_destino(False)

    def test_autorizacion_destino_sigue_obligatoria(self):
        UbicacionEmpresa.objects.filter(empresa=self.empresa, ubicacion=self.destino).update(permite_destino=False)
        self._comprobar_destino(False)

    def test_solicitante_solo_elige_su_origen_pero_ve_destinos_del_departamento(self):
        self.solicitante.sucursal = self.sucursal_origen
        self.solicitante.save(update_fields=("sucursal", "actualizado_en"))
        RolUsuario.objetos.filter(usuario=self.solicitante).update(activo=False, revocado_en=timezone.now())
        RolUsuario.objetos.create(usuario=self.solicitante, rol=Rol.objetos.get(codigo="SOLICITANTE_CORPORATIVO"), tipo_alcance="SUCURSAL", empresa=self.empresa, sucursal=self.sucursal_origen, asignado_por=self.administrador)
        Ubicacion.objects.filter(pk=self.destino.pk).update(localidad="Comayagüela")
        opciones = self._opciones()
        self.assertEqual([p["sucursal_id"] for p in opciones["origenes"]], [str(self.sucursal_origen.pk)])
        self.assertIn(str(self.destino.pk), {p["ubicacion"]["id"] for p in opciones["destinos"]})

    def test_empresa_transporte_no_adquiere_restriccion_departamental(self):
        Ubicacion.objects.filter(pk=self.empresa_transporte.pk).update(nivel_administrativo_1="Cortés")
        solicitud = crear_solicitud(self.gerente, self._datos_creacion("EMPRESA_TRANSPORTE", destino_id=self.empresa_transporte.pk))
        self.assertEqual(solicitud.destino_id, self.empresa_transporte.pk)

    def test_especial_sin_destino_no_requiere_departamento(self):
        Ubicacion.objects.filter(pk=self.origen.pk).update(nivel_administrativo_1=None)
        solicitud = crear_solicitud(self.gerente, self._datos_creacion("ESPECIAL", destino_id=None, destino_especial="Encargo de prueba"))
        self.assertIsNone(solicitud.destino_id)

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_no_habilita_creacion_network_ni_le_impone_esta_regla(self):
        with self.assertRaises(CreacionSolicitudNoDisponible):
            crear_solicitud(self.gerente, self._datos_creacion("ENTRE_SUCURSALES"))
        with self.assertRaises(CreacionSolicitudNoDisponible):
            obtener_opciones_creacion_solicitud(self.gerente, {"empresa_id": self.empresa.pk})
