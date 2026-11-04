"""Un GPS no recorre la cola con la flota llena; la disponibilidad se revalida."""

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.flota.models import Vehiculo
from apps.jornadas.models import JornadaRepartidor
from apps.repartidores.models import Repartidor
from apps.seguimiento.models import RegistroUbicacion
from apps.seguimiento.servicios import registrar_ubicaciones
from apps.seguimiento.tests import test_seguimiento as datos
from apps.solicitudes.models import AsignacionSolicitud, Solicitud
from apps.usuarios.models import Rol, RolUsuario, Usuario


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasReintentosGPS(TestCase):
    setUpTestData = classmethod(datos.PruebasSeguimiento.setUpTestData.__func__)

    def setUp(self):
        ahora = timezone.now().astimezone(ZoneInfo("America/Tegucigalpa")).replace(hour=12, minute=0, second=0)
        self.enterContext(patch("django.utils.timezone.now", return_value=ahora))
        self.enterContext(patch("apps.rutas.proveedor_google.urlopen", side_effect=AssertionError("Sin Google.")))
        datos.PruebasSeguimiento.setUp(self)
        self.jornada.cierre_programado_en = self.ahora.replace(hour=22)
        self.jornada.save(update_fields=("cierre_programado_en",))
        for i in range(4):
            self._pedido(f"ACTIVO-{i}", repartidor=self.repartidor)

    def _pedido(self, numero, *, repartidor=None):
        pedido = Solicitud.objects.create(numero=numero, empresa=self.empresa, solicitada_por=self.administrador,
            prioridad="NORMAL", origen=self.origen, destino=self.destino, cantidad_tubos=1, cantidad_frascos=1,
            repartidor_asignado=repartidor, estado="GOING_TO_PICKUP" if repartidor else "PENDING")
        if repartidor:
            AsignacionSolicitud.objects.create(solicitud=pedido, repartidor=repartidor, asignada_por=self.administrador,
                asignada_en=self.ahora-timedelta(minutes=1), aceptada_en=self.ahora-timedelta(minutes=1))
        return pedido

    def _enviar(self):
        punto = datos.PruebasSeguimiento._registro(self, self.ahora)
        punto["latitud"], punto["longitud"] = "14.095000", "-87.200000"
        with CaptureQueriesContext(connection) as consultas:
            with self.captureOnCommitCallbacks(execute=True):
                resultado = registrar_ubicaciones(self.usuario_repartidor, {
                    "jornada_id": self.jornada.pk, "registros": [punto],
                })
        self.assertEqual(resultado["creados"], 1)
        return len(consultas)

    def test_cincuenta_pendientes_no_incrementan_consultas_con_flota_llena(self):
        self._pedido("PENDIENTE-0")
        pocas = self._enviar()
        for i in range(1, 50):
            self._pedido(f"PENDIENTE-{i}")
        muchas = self._enviar()
        self.assertLessEqual(muchas, pocas+2)
        self.assertEqual(Solicitud.objects.filter(estado="PENDING").count(), 50)

    def test_liberar_cupo_permita_asignar_en_el_siguiente_gps(self):
        pendiente = self._pedido("PENDIENTE-CUPO")
        self._enviar()
        pendiente.refresh_from_db()
        self.assertIsNone(pendiente.repartidor_asignado_id)
        self.solicitud.estado = "DELIVERED"
        self.solicitud.save(update_fields=("estado",))
        self.asignacion.estado = "FINALIZADA"
        self.asignacion.finalizada_en = self.ahora
        self.asignacion.save(update_fields=("estado", "finalizada_en"))
        self._enviar()
        pendiente.refresh_from_db()
        self.assertEqual(pendiente.repartidor_asignado_id, self.repartidor.pk)

    def test_gps_de_motorista_lleno_asigna_a_otro_con_cupo_y_gps_vigente(self):
        usuario = Usuario.objetos.create(correo="otro-gps@example.test", nombres="Otro", apellidos="Motorista", empresa=self.empresa)
        rol = Rol.objetos.get(codigo="REPARTIDOR_CORPORATIVO")
        RolUsuario.objetos.create(usuario=usuario, rol=rol, tipo_alcance="EMPRESA", empresa=self.empresa)
        vehiculo = Vehiculo.objects.create(empresa=self.empresa, placa="OTRO-GPS", tipo="MOTOCICLETA")
        otro = Repartidor.objects.create(usuario=usuario, empresa=self.empresa, vehiculo=vehiculo,
            pais_operacion=self.pais, departamento_operacion="Francisco Morazán", estado_operativo="AVAILABLE")
        jornada = JornadaRepartidor.objects.create(repartidor=otro, iniciada_en=self.ahora-timedelta(hours=1),
            cierre_programado_en=self.ahora.replace(hour=22))
        punto = RegistroUbicacion.objects.create(id_cliente=uuid4(), repartidor=otro, jornada=jornada,
            registrada_en=self.ahora-timedelta(minutes=3), latitud=self.origen.latitud,
            longitud=self.origen.longitud, precision_metros=5)
        pendiente = self._pedido("PENDIENTE-OTRO")
        self._enviar()
        pendiente.refresh_from_db()
        self.assertIsNone(pendiente.repartidor_asignado_id)
        RegistroUbicacion.objects.filter(pk=punto.pk).update(registrada_en=self.ahora)
        self._enviar()
        pendiente.refresh_from_db()
        self.assertEqual(pendiente.repartidor_asignado_id, otro.pk)
