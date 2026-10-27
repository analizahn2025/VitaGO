"""El cierre libera cupo, pero nunca levanta una indisponibilidad explícita."""

from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.evidencias.servicios import registrar_evidencia
from apps.nucleo.tests.imagenes import crear_imagen_prueba
from apps.repartidores.capacidad import puede_recibir_solicitudes
from apps.repartidores.servicios import actualizar_operacion_repartidor
from apps.seguimiento.tests import test_seguimiento as datos_seguimiento
from apps.solicitudes.models import AsignacionSolicitud, Solicitud
from apps.solicitudes.opciones import EstadoSolicitud
from apps.solicitudes.servicios import cambiar_estado_solicitud


@override_settings(MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL")
class PruebasDisponibilidadTrasCierre(TestCase):
    setUpTestData = classmethod(
        datos_seguimiento.PruebasSeguimiento.setUpTestData.__func__
    )
    setUp = datos_seguimiento.PruebasSeguimiento.setUp

    def _comprobar_cierre(self, estado_operativo, destino, con_otra):
        # Cada combinación vuelve a los mismos datos iniciales al salir.
        with transaction.atomic():
            self.solicitud.refresh_from_db()
            self.repartidor.refresh_from_db()
            self.solicitud.estado = (
                EstadoSolicitud.EN_RECOLECCION
                if destino == EstadoSolicitud.RECOLECCION_FALLIDA
                else EstadoSolicitud.EN_DESTINO
                if destino in (EstadoSolicitud.ENTREGADA, EstadoSolicitud.ENTREGA_FALLIDA)
                else EstadoSolicitud.HACIA_RECOLECCION
            )
            self.solicitud.save()
            if con_otra:
                otra = Solicitud.objects.create(
                    cantidad_tubos=1,
                    numero="OTRA-ACTIVA", empresa=self.empresa,
                    solicitada_por=self.solicitante, repartidor_asignado=self.repartidor,
                    prioridad="NORMAL", tipo_servicio=self.tipo_servicio,
                    origen=self.origen, destino=self.destino, estado=EstadoSolicitud.ASIGNADA,
                )
                AsignacionSolicitud.objects.create(
                    solicitud=otra, repartidor=self.repartidor,
                    asignada_por=self.administrador,
                )
            if self.repartidor.estado_operativo != estado_operativo:
                actualizar_operacion_repartidor(self.usuario_repartidor, self.repartidor.pk, {
                    "estado_operativo": estado_operativo, "motivo": "Prueba de disponibilidad",
                })
            if destino == EstadoSolicitud.ENTREGADA:
                registrar_evidencia(self.usuario_repartidor, self.solicitud.pk, {
                    "tipo": "FOTO_ENTREGA", "archivo": crear_imagen_prueba(),
                    "latitud": self.origen.latitud, "longitud": self.origen.longitud,
                    "capturada_en": timezone.now(),
                })
            else:
                cambiar_estado_solicitud(
                    self.administrador if destino == EstadoSolicitud.CANCELADA else self.usuario_repartidor,
                    self.solicitud.pk, {"estado_destino": destino, "motivo": "Cierre de prueba"},
                )
            self.repartidor.refresh_from_db()
            bloqueado = estado_operativo in ("PAUSED", "OFFLINE", "OUT_OF_SERVICE")
            esperado = estado_operativo if bloqueado else "ON_ROUTE" if con_otra else "AVAILABLE"
            self.assertEqual(self.repartidor.estado_operativo, esperado)
            self.assertEqual(self.repartidor.capacidad, "AVAILABLE_SPACE" if con_otra else "EMPTY")
            self.assertEqual(puede_recibir_solicitudes(self.repartidor), not bloqueado)
            self.asignacion.refresh_from_db()
            self.assertNotEqual(self.asignacion.estado, "ACTIVA")
            transaction.set_rollback(True)

    def test_cierres_conservan_pausa_desconexion_y_fuera_de_servicio(self):
        for estado in ("PAUSED", "OFFLINE", "OUT_OF_SERVICE"):
            for destino in (
                EstadoSolicitud.CANCELADA, EstadoSolicitud.RECOLECCION_FALLIDA,
                EstadoSolicitud.ENTREGA_FALLIDA, EstadoSolicitud.ENTREGADA,
            ):
                for con_otra in (False, True):
                    with self.subTest(estado=estado, destino=destino, con_otra=con_otra):
                        self._comprobar_cierre(estado, destino, con_otra)

    def test_cierres_conservan_disponibilidad_automatica_para_motoristas_operativos(self):
        for estado in ("AVAILABLE", "ON_ROUTE"):
            for destino in (
                EstadoSolicitud.CANCELADA, EstadoSolicitud.RECOLECCION_FALLIDA,
                EstadoSolicitud.ENTREGA_FALLIDA, EstadoSolicitud.ENTREGADA,
            ):
                for con_otra in (False, True):
                    with self.subTest(estado=estado, destino=destino, con_otra=con_otra):
                        self._comprobar_cierre(estado, destino, con_otra)
