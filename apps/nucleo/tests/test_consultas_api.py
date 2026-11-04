"""Regresiones de rendimiento y aislamiento de las consultas HTTP."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo
from uuid import uuid4
from urllib.parse import parse_qsl, urlsplit

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.evidencias.models import EvidenciaSolicitud
from apps.incidencias.models import Incidencia
from apps.jornadas.models import JornadaRepartidor
from apps.notificaciones.models import NotificacionUsuario
from apps.organizaciones.models import Sucursal
from apps.rutas.servicios import sincronizar_ruta
from apps.seguimiento.models import RegistroUbicacion
from apps.solicitudes.models import AsignacionSolicitud, EventoSolicitud, Solicitud
from apps.solicitudes.tests import test_asignaciones as datos
from apps.ubicaciones.models import UbicacionEmpresa
from apps.usuarios.models import Permiso, PermisoRol, Rol, RolUsuario, Usuario


class PruebasConsultasAPI(TestCase):
    setUpTestData = classmethod(datos.PruebasAsignacionesSolicitud.setUpTestData.__func__)

    def setUp(self):
        self.ahora = datetime(2026, 11, 4, 12, tzinfo=ZoneInfo('America/Tegucigalpa'))
        self.enterContext(patch('django.utils.timezone.now', return_value=self.ahora))
        self.enterContext(patch('apps.rutas.proveedor_google.urlopen', side_effect=AssertionError('Sin red.')))
        self.cliente = APIClient()
        rol = Rol.objetos.create(codigo='LECTOR_AUDITORIA', nombre='Lector de auditoría', permite_alcance_empresa=True)
        PermisoRol.objetos.bulk_create([PermisoRol(rol=rol, permiso=p) for p in Permiso.objetos.filter(activo=True)])
        self.lector = Usuario.objetos.create(correo='lector.auditoria@example.test', nombres='Lector', empresa=self.empresa)
        RolUsuario.objetos.create(usuario=self.lector, rol=rol, tipo_alcance='EMPRESA', empresa=self.empresa, asignado_por=self.administrador)
        self.motorista = self.repartidores[0]
        self.sucursales = []
        for i, ubicacion in enumerate((self.origen, self.destino)):
            self.sucursales.append(Sucursal.objects.create(empresa=self.empresa, ubicacion=ubicacion, nombre=f'Sucursal {i}'))
            UbicacionEmpresa.objects.create(empresa=self.empresa, ubicacion=ubicacion, estado='APROBADO', permite_origen=True, permite_destino=True)
        self.jornada = JornadaRepartidor.objects.create(repartidor=self.motorista, iniciada_en=self.ahora-timedelta(hours=1),
            fecha_operativa=self.ahora.date(), cierre_programado_en=self.ahora.replace(hour=22))
        for i in range(3):
            solicitud = Solicitud.objects.create(numero=f'AUD-{i}', empresa=self.empresa, sucursal=self.sucursales[0],
                solicitada_por=self.lector, origen=self.origen, destino=self.destino, tipo_servicio=self.tipo_servicio,
                cantidad_tubos=1, cantidad_frascos=1, repartidor_asignado=self.motorista,
                modalidad='ENTRE_SUCURSALES', prioridad='NORMAL', estado='GOING_TO_PICKUP', asignada_en=self.ahora-timedelta(minutes=30))
            AsignacionSolicitud.objects.create(solicitud=solicitud, repartidor=self.motorista, asignada_por=self.administrador,
                asignada_en=solicitud.asignada_en, aceptada_en=solicitud.asignada_en, estado='ACTIVA')
            evento = EventoSolicitud.objects.create(solicitud=solicitud, tipo='ASIGNADA', realizado_por=self.administrador, repartidor=self.motorista)
            NotificacionUsuario.objects.create(usuario=self.lector, solicitud=solicitud, evento=evento, tipo='SOLICITUD_ASIGNADA', titulo='Servicio de prueba', mensaje='Prueba')
            EvidenciaSolicitud.objects.create(solicitud=solicitud, repartidor=self.motorista, tipo='FOTO_RECOLECCION', temperatura_contenedor_c='4.00', fuente_temperatura='MANUAL',
                capturada_en=self.ahora-timedelta(minutes=15), clave_almacenamiento=f'prueba-{i}.png', tipo_contenido='image/png', tamano_bytes=100,
                latitud=self.origen.latitud, longitud=self.origen.longitud)
            self.solicitud = solicitud
        self.incidencia = Incidencia.objects.create(jornada=self.jornada, repartidor=self.motorista, solicitud=self.solicitud,
            descripcion='Incidencia de prueba', reportada_en=self.ahora)
        RegistroUbicacion.objects.create(id_cliente=uuid4(), repartidor=self.motorista, jornada=self.jornada, registrada_en=self.ahora,
            latitud=self.origen.latitud, longitud=self.origen.longitud, precision_metros=5, es_operativo=True, sesion_gps=uuid4(), secuencia=1)
        self.ruta = sincronizar_ruta(self.motorista, 'INICIAL', jornada=self.jornada)

    def _get(self, ruta, *, usuario=None, **parametros):
        self.cliente.force_authenticate(
            Usuario.objetos.get(pk=(usuario or self.lector).pk),
        )
        with CaptureQueriesContext(connection) as consultas:
            partes = urlsplit(ruta)
            respuesta = self.cliente.get('/api/v1/'+partes.path, {**dict(parse_qsl(partes.query)), **parametros})
        self.assertEqual(respuesta.status_code, 200, respuesta.json())
        return respuesta.json(), consultas.captured_queries

    def test_listados_no_agregan_consultas_por_cada_fila(self):
        rutas = (
            'usuarios/', 'organizaciones/empresas/',
            f'organizaciones/empresas/{self.empresa.pk}/sucursales/',
            f'ubicaciones/?empresa_id={self.empresa.pk}', 'vehiculos/',
            'repartidores/', 'notificaciones/', 'solicitudes/', 'jornadas/',
            'incidencias/', 'rutas/', 'seguimiento/motoristas/',
            f'rutas/{self.ruta.pk}/versiones/',
        )
        for ruta in rutas:
            with self.subTest(ruta=ruta):
                pocos, consultas_pocos = self._get(ruta, tamano_pagina=1)
                todos, consultas_todos = self._get(ruta, tamano_pagina=20)
                self.assertEqual(pocos['conteo'], todos['conteo'])
                self.assertEqual(len(consultas_pocos), len(consultas_todos))
                self.assertNotIn('contenido_base64', ' '.join(c['sql'] for c in consultas_todos))

    def test_seguimiento_y_evidencias_no_traen_historial_completo(self):
        tablas_historial = ('articulos_solicitud', EventoSolicitud._meta.db_table,
                            'movimientos_envios_especiales')
        for sufijo, maximo in (('seguimiento/', 6), ('evidencias/', 5)):
            with self.subTest(sufijo=sufijo):
                _, consultas = self._get(f'solicitudes/{self.solicitud.pk}/{sufijo}')
                self.assertLessEqual(len(consultas), maximo)
                sql = ' '.join(c['sql'] for c in consultas)
                for tabla in tablas_historial:
                    self.assertNotIn('"'+tabla+'"', sql)
                self.assertNotIn('contenido_base64', sql)

    def test_detalle_conserva_eventos_y_asignaciones(self):
        respuesta, consultas = self._get(f'solicitudes/{self.solicitud.pk}/')
        self.assertEqual(respuesta['eventos'][0]['tipo'], 'ASIGNADA')
        self.assertEqual(respuesta['asignaciones'][0]['repartidor_id'], str(self.motorista.pk))
        self.assertLessEqual(len(consultas), 6)

    def test_revocar_rol_se_aplica_en_la_siguiente_lectura(self):
        rutas = ('usuarios/', 'solicitudes/', 'jornadas/', 'rutas/', 'incidencias/',
                 f'solicitudes/{self.solicitud.pk}/seguimiento/',
                 f'solicitudes/{self.solicitud.pk}/evidencias/')
        for ruta in rutas:
            self._get(ruta)
        RolUsuario.objetos.filter(usuario=self.lector).update(activo=False, revocado_en=self.ahora)
        for ruta in rutas:
            with self.subTest(ruta=ruta):
                self.assertEqual(self.cliente.get('/api/v1/'+ruta).status_code, 403)

    def test_lecturas_ligeras_conservan_aislamiento_por_empresa(self):
        ajena = self.empresa.__class__.objects.create(nombre='Otra empresa', pais=self.pais)
        solicitud = Solicitud.objects.create(numero='AJENA', empresa=ajena, solicitada_por=self.administrador,
            origen=self.origen, destino=self.destino, cantidad_tubos=1, cantidad_frascos=1, prioridad='NORMAL')
        self.cliente.force_authenticate(self.lector)
        for sufijo in ('', 'seguimiento/', 'evidencias/'):
            with self.subTest(sufijo=sufijo):
                respuesta = self.cliente.get(f'/api/v1/solicitudes/{solicitud.pk}/{sufijo}')
                self.assertEqual(respuesta.status_code, 404)

    def test_jornada_activa_reutiliza_motorista_y_estado_vigente(self):
        respuesta, consultas = self._get('jornadas/activa/', usuario=self.motorista.usuario)
        self.assertTrue(respuesta['jornada_iniciada_hoy'])
        self.assertFalse(respuesta['puede_iniciar_jornada'])
        self.assertLessEqual(len(consultas), 5)

    def test_carga_actual_no_cuenta_historial_terminal(self):
        from apps.repartidores.selectores import listar_repartidores_autorizados

        Solicitud.objects.bulk_create([
            Solicitud(numero=f'HIST-{i}', empresa=self.empresa, solicitada_por=self.lector,
                origen=self.origen, destino=self.destino, repartidor_asignado=self.motorista,
                estado=estado, cantidad_tubos=20, cantidad_frascos=20, prioridad='NORMAL')
            for i, estado in enumerate(('DELIVERED', 'CANCELLED', 'PICKUP_FAILED', 'DELIVERY_FAILED', 'PENDING'))
        ])
        repartidor = listar_repartidores_autorizados(self.lector).get(pk=self.motorista.pk)
        self.assertEqual(repartidor.solicitudes_activas_calculadas, 3)
        self.assertEqual((repartidor.tubos_comprometidos, repartidor.frascos_comprometidos), (3, 3))
        sin_servicios = listar_repartidores_autorizados(self.lector).get(pk=self.repartidores[1].pk)
        self.assertEqual(sin_servicios.solicitudes_activas_calculadas, 0)

    def test_ruta_fallida_carga_version_sin_consulta_adicional(self):
        from apps.rutas.models import CalculoRutaVial
        from apps.rutas.ruta_vial import presentar_ruta_vial
        from apps.rutas.selectores import obtener_paradas_operativas

        CalculoRutaVial.objects.create(
            version=self.ruta.versiones.get(numero=1), estado='FALLIDA',
            iniciada_en=self.ahora, token_intento=uuid4(), codigo_error='PRUEBA',
        )
        paradas = obtener_paradas_operativas(self.motorista)
        with self.assertNumQueries(2):
            respuesta = presentar_ruta_vial(self.ruta, paradas, 1)
        self.assertEqual(respuesta['estado'], 'FALLIDA')
        self.assertEqual(respuesta['version_calculada'], 1)


@override_settings(MODO_APLICACION='EXTERNO')
class PruebasConsultasNetwork(PruebasConsultasAPI):
    def setUp(self):
        super().setUp()
        Rol.objetos.filter(codigo='LECTOR_AUDITORIA').update(permite_alcance_global=True)
        RolUsuario.objetos.filter(usuario=self.lector).update(tipo_alcance='GLOBAL', empresa=None)
        rol_network = Rol.objetos.get(codigo='REPARTIDOR_RED')
        for repartidor in self.repartidores:
            RolUsuario.objetos.filter(usuario_id=repartidor.usuario_id).update(
                rol=rol_network, tipo_alcance='GLOBAL', empresa=None,
            )
            repartidor.usuario.empresa = None
            repartidor.usuario.save(update_fields=('empresa',))
            repartidor.vehiculo.empresa = None
            repartidor.vehiculo.save(update_fields=('empresa',))
            repartidor.empresa = None
            repartidor.save(update_fields=('empresa',))

    def test_lecturas_ligeras_conservan_aislamiento_por_empresa(self):
        # Un cliente Network acotado a su empresa tampoco ve otras empresas.
        RolUsuario.objetos.filter(usuario=self.lector).update(tipo_alcance='EMPRESA', empresa=self.empresa)
        super().test_lecturas_ligeras_conservan_aislamiento_por_empresa()

