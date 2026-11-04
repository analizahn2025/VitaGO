"""Segmentación por país/departamento administrado, previa a la cercanía GPS."""

from unittest.mock import patch

from django.db import transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.geografia.models import Pais
from apps.repartidores.capacidad import puede_recibir_solicitudes
from apps.repartidores.models import HistorialEstadoRepartidor, Repartidor
from apps.repartidores.servicios import actualizar_cobertura_repartidor, crear_repartidor
from apps.solicitudes.asignacion_automatica import candidatos_ordenados
from apps.solicitudes.servicios import asignar_solicitud_manualmente
from apps.solicitudes.tests import test_asignaciones as datos
from apps.solicitudes.tests import test_alcance_flotas as datos_flotas
from apps.ubicaciones.models import UbicacionEmpresa
from apps.usuarios.models import Usuario, Rol, RolUsuario


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasCoberturaDepartamentos(TestCase):
    setUpTestData = classmethod(datos.PruebasAsignacionesSolicitud.setUpTestData.__func__)
    _registrar_gps = datos.PruebasAsignacionesSolicitud._registrar_gps
    _motorista = datos_flotas.PruebasAlcanceFlotas._motorista

    def setUp(self):
        datos.PruebasAsignacionesSolicitud.setUp(self)
        self.primero, self.segundo = self.repartidores
        self.cliente = APIClient()
        self.cliente.force_authenticate(self.administrador)
        self.enterContext(patch("apps.rutas.proveedor_google.urlopen", side_effect=AssertionError("Sin consultas Google.")))

    def _departamento(self, repartidor, nombre, pais=None):
        repartidor.pais_operacion = pais or self.pais
        repartidor.departamento_operacion = nombre
        repartidor.save(update_fields=("pais_operacion", "departamento_operacion", "actualizado_en"))

    def _patch(self, repartidor=None, **cambios):
        return self.cliente.patch(reverse("repartidores:cobertura", args=[(repartidor or self.primero).pk]),
            {"departamento_operacion": "Cortés", "motivo": "Asignación administrativa de territorio", **cambios}, format="json")

    def test_departamento_se_filtra_antes_que_distancia_gps(self):
        self._departamento(self.primero, "Cortés")
        self._registrar_gps(self.primero, "14.072300", "-87.192100")
        self._registrar_gps(self.segundo, "14.102300", "-87.192100")
        candidatos = candidatos_ordenados(self.solicitud)
        self.assertEqual([identificador for identificador,_ in candidatos], [self.segundo.pk])

    def test_asignacion_manual_rechaza_otro_departamento(self):
        self._departamento(self.primero, "Cortés")
        with self.assertRaises(ValidationError) as error:
            asignar_solicitud_manualmente(self.administrador,self.solicitud.pk,{"repartidor_id":self.primero.pk})
        self.assertIn("repartidor_id",error.exception.detail)
        self.solicitud.refresh_from_db()
        self.assertIsNone(self.solicitud.repartidor_asignado_id)

    def test_manual_permite_mismo_departamento_y_normaliza_acentos(self):
        self._departamento(self.primero,"  FRANCISCO   MORAZAN ")
        resultado=asignar_solicitud_manualmente(self.administrador,self.solicitud.pk,{"repartidor_id":self.primero.pk})
        self.assertEqual(resultado.repartidor_asignado_id,self.primero.pk)

    def test_gps_en_otro_lugar_no_cambia_departamento_fijo(self):
        self._departamento(self.primero,"Cortés")
        self._registrar_gps(self.primero,str(self.origen.latitud),str(self.origen.longitud))
        self.primero.refresh_from_db()
        self.assertEqual(self.primero.departamento_operacion,"Cortés")
        self.assertNotIn(self.primero.pk,[i for i,_ in candidatos_ordenados(self.solicitud)])

    def test_origen_sin_departamento_no_tiene_candidatos(self):
        self.origen.nivel_administrativo_1=None
        self.origen.save()
        self.assertEqual(candidatos_ordenados(self.solicitud),[])
        with self.assertRaises(ValidationError) as error:
            asignar_solicitud_manualmente(self.administrador,self.solicitud.pk,{"repartidor_id":self.primero.pk})
        self.assertIn("origen_id",error.exception.detail)

    def test_perfil_sin_cobertura_no_puede_recibir_solicitudes(self):
        self.primero.pais_operacion=None
        self.primero.departamento_operacion=""
        self.primero.save()
        self.assertFalse(puede_recibir_solicitudes(self.primero))
        self.assertNotIn(self.primero.pk,[i for i,_ in candidatos_ordenados(self.solicitud)])
        respuesta=self.cliente.get(reverse("repartidores:detalle",args=[self.primero.pk]))
        self.assertFalse(respuesta.data["cobertura_configurada"])

    def test_admin_configura_departamento_y_queda_auditado(self):
        r=self._patch()
        self.assertEqual(r.status_code,200,r.data)
        self.assertEqual(r.data["pais_operacion_id"],self.pais.pk)
        self.assertEqual(r.data["departamento_operacion"],"Cortés")
        self.assertTrue(r.data["cobertura_configurada"])
        historial=HistorialEstadoRepartidor.objects.filter(repartidor=self.primero).first()
        self.assertEqual(historial.realizado_por_id,self.administrador.pk)
        self.assertEqual(historial.datos_adicionales["cobertura_nueva"]["departamento_operacion"],"Cortés")

    def test_motorista_no_puede_cambiar_su_propio_departamento(self):
        self.cliente.force_authenticate(self.primero.usuario)
        self.assertEqual(self._patch().status_code,403)
        self.primero.refresh_from_db()
        self.assertEqual(self.primero.departamento_operacion,"Francisco Morazán")

    def test_con_servicios_activos_no_se_puede_cambiar_departamento(self):
        asignar_solicitud_manualmente(self.administrador,self.solicitud.pk,{"repartidor_id":self.primero.pk})
        r=self._patch()
        self.assertEqual(r.status_code,400)
        self.assertIn("departamento_operacion",r.data)

    def test_configuracion_exige_motivo_y_rechaza_capacidad(self):
        r=self._patch(motivo="")
        self.assertEqual(r.status_code,400)
        self.assertIn("motivo",r.data)
        r=self._patch(capacidad="FULL")
        self.assertEqual(r.status_code,400)
        self.assertIn("capacidad",r.data)

    def test_corporate_rechaza_pais_ajeno_a_la_empresa(self):
        pais=Pais.objects.create(iso2="SV",iso3="SLV",nombre="Otro país",codigo_telefonico="+503",codigo_moneda="USD",zona_horaria_predeterminada="America/El_Salvador")
        r=self._patch(pais_operacion_id=str(pais.pk))
        self.assertEqual(r.status_code,400)
        self.assertIn("pais_operacion_id",r.data)

    def test_disponibles_de_solicitud_no_muestra_otro_departamento(self):
        self._departamento(self.primero,"Cortés")
        r=self.cliente.get(reverse("repartidores:disponibles"),{"solicitud_id":str(self.solicitud.pk)})
        self.assertEqual(r.status_code,200,r.data)
        self.assertEqual({fila["id"] for fila in r.data["resultados"]},{str(self.segundo.pk)})

    def test_opciones_departamentales_vacias_no_generan_error(self):
        r=self.cliente.get(reverse("repartidores:departamentos"),{"empresa_id":self.empresa.pk})
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.data,{"departamentos":[]})

    def test_opciones_departamentales_salen_de_ubicaciones_autorizadas(self):
        UbicacionEmpresa.objects.create(empresa=self.empresa,ubicacion=self.origen,estado="APROBADO",permite_origen=True)
        r=self.cliente.get(reverse("repartidores:departamentos"),{"empresa_id":self.empresa.pk})
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.data["departamentos"][0]["departamento_operacion"],"Francisco Morazán")

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_aplica_departamento_a_la_flota_compartida(self):
        cercano=self._motorista()
        permitido=self._motorista()
        self._departamento(cercano,"Cortés")
        self.assertEqual([i for i,_ in candidatos_ordenados(self.solicitud)],[permitido.pk])
        with self.assertRaises(ValidationError):
            asignar_solicitud_manualmente(self.administrador,self.solicitud.pk,{"repartidor_id":cercano.pk})
        asignada=asignar_solicitud_manualmente(self.administrador,self.solicitud.pk,{"repartidor_id":permitido.pk})
        self.assertEqual(asignada.repartidor_asignado_id,permitido.pk)

    @override_settings(MODO_APLICACION="EXTERNO")
    def test_network_exige_pais_y_cliente_no_administra_cobertura(self):
        repartidor=self._motorista()
        r=self._patch(repartidor)
        self.assertEqual(r.status_code,400)
        self.assertIn("pais_operacion_id",r.data)
        r=self._patch(repartidor,pais_operacion_id=str(self.pais.pk))
        self.assertEqual(r.status_code,200,r.data)

    def test_lector_de_otra_empresa_no_puede_modificar_cobertura(self):
        usuario=Usuario.objetos.create(correo="sin.cobertura@example.test",nombres="Sin permiso")
        self.cliente.force_authenticate(usuario)
        self.assertEqual(self._patch().status_code,403)

    def test_legacy_sin_departamento_no_se_infiere_del_usuario(self):
        usuario=Usuario.objetos.create(correo="legacy.cobertura@example.test",empresa=self.empresa)
        perfil=Repartidor.objects.create(usuario=usuario,empresa=self.empresa)
        self.assertIsNone(perfil.pais_operacion_id)
        self.assertEqual(perfil.departamento_operacion,"")
        self.assertFalse(perfil.cobertura_configurada)
