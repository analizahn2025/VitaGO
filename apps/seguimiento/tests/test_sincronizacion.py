from datetime import timedelta
from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.jornadas.models import JornadaRepartidor
from apps.jornadas.servicios import confirmar_sincronizacion_jornada, finalizar_jornada
from apps.seguimiento.models import RegistroUbicacion, RevisionKilometraje
from apps.seguimiento.serializadores import SerializadorLoteRegistrosUbicacion
from apps.seguimiento.servicios import registrar_ubicaciones
from apps.seguimiento.tests.test_seguimiento import PruebasSeguimiento
from apps.solicitudes.models import Solicitud
from apps.solicitudes.opciones import EstadoAsignacionSolicitud, EstadoSolicitud
from apps.solicitudes.servicios import cambiar_estado_solicitud


class PruebasSincronizacionGPS(PruebasSeguimiento):
    def preparar_especial_finalizado(self):
        from apps.solicitudes.servicios_movimientos import iniciar_movimiento_especial, cerrar_movimiento_especial

        self.solicitud.modalidad = "ESPECIAL"
        self.solicitud.destino = None
        self.solicitud.destino_especial = "Encargo de prueba"
        self.solicitud.save()
        inicio = self.ahora - timedelta(minutes=4)
        movimiento = iniciar_movimiento_especial(
            self.solicitud, self.repartidor, latitud=Decimal("14"), longitud=Decimal("-87"), ahora=inicio,
        )
        fin = inicio + timedelta(seconds=40)
        cerrar_movimiento_especial(
            self.solicitud, self.repartidor, latitud=Decimal("14.0004"), longitud=Decimal("-87"), ahora=fin,
        )
        self.solicitud.estado = EstadoSolicitud.ENTREGADA
        self.solicitud.entregada_en = fin
        self.solicitud.save()
        self.asignacion.estado = EstadoAsignacionSolicitud.FINALIZADA
        self.asignacion.finalizada_en = fin
        self.asignacion.save()
        return movimiento

    def test_confirmacion_especial_bloquea_solo_solicitud_y_es_idempotente(self):
        movimiento = self.preparar_especial_finalizado()
        cliente = APIClient()
        cliente.force_authenticate(self.usuario_repartidor)
        url = reverse("solicitudes:sincronizacion-gps", args=[self.solicitud.id])
        # SQLite no reproduce el error del JOIN nullable de PostgreSQL:
        # conservar explícitamente el alcance del bloqueo en el contrato del servicio.
        with patch.object(Solicitud.objects, "select_for_update", wraps=Solicitud.objects.select_for_update) as bloquear:
            respuesta = cliente.post(url, {"sesiones_gps": []}, format="json")
        self.assertEqual(respuesta.status_code, 200)
        bloquear.assert_called_once_with(of=("self",), no_key=True)
        movimiento.refresh_from_db()
        self.assertTrue(movimiento.calidad_kilometraje["sincronizacion_verificada"])
        cantidad = RevisionKilometraje.objects.filter(movimiento_especial=movimiento).count()
        self.assertEqual(cliente.post(url, {"sesiones_gps": []}, format="json").status_code, 200)
        self.assertEqual(RevisionKilometraje.objects.filter(movimiento_especial=movimiento).count(), cantidad)

    def test_confirmacion_especial_permite_jornada_ya_finalizada(self):
        movimiento = self.preparar_especial_finalizado()
        finalizar_jornada(self.usuario_repartidor, self.jornada.id, {})
        cliente = APIClient()
        cliente.force_authenticate(self.usuario_repartidor)
        respuesta = cliente.post(
            reverse("solicitudes:sincronizacion-gps", args=[self.solicitud.id]), {"sesiones_gps": []}, format="json",
        )
        self.assertEqual(respuesta.status_code, 200)
        movimiento.refresh_from_db()
        self.assertTrue(movimiento.calidad_kilometraje["sincronizacion_verificada"])

    def test_confirmacion_especial_rechaza_a_otro_usuario(self):
        movimiento = self.preparar_especial_finalizado()
        cliente = APIClient()
        cliente.force_authenticate(self.solicitante)
        respuesta = cliente.post(
            reverse("solicitudes:sincronizacion-gps", args=[self.solicitud.id]), {"sesiones_gps": []}, format="json",
        )
        self.assertEqual(respuesta.status_code, 403)
        movimiento.refresh_from_db()
        self.assertFalse(movimiento.calidad_kilometraje["sincronizacion_verificada"])

    def test_especial_verificado_bloquea_puntos_nuevos_en_todo_el_prefijo(self):
        from apps.solicitudes.servicios_movimientos import confirmar_sincronizacion_movimiento

        movimiento = self.preparar_especial_finalizado()
        confirmar_sincronizacion_movimiento(self.usuario_repartidor, self.solicitud.pk, {"sesiones_gps": []})
        movimiento.refresh_from_db()
        calidad = dict(movimiento.calidad_kilometraje)
        revisiones = RevisionKilometraje.objects.filter(movimiento_especial=movimiento).count()
        for segundos in (-20, 0, 20, 40):
            with self.subTest(segundos=segundos):
                punto = {**self._registro(movimiento.iniciada_en + timedelta(seconds=segundos)),
                         "sesion_gps": uuid4(), "secuencia": 1}
                with self.assertRaises(ValidationError) as rechazo:
                    registrar_ubicaciones(self.usuario_repartidor, {"jornada_id": self.jornada.pk, "registros": [punto]})
                self.assertIn("registrada_en", rechazo.exception.detail["registros"][0])
        movimiento.refresh_from_db()
        self.assertEqual(RegistroUbicacion.objects.filter(jornada=self.jornada).count(), 0)
        self.assertEqual(movimiento.calidad_kilometraje, calidad)
        self.assertEqual(RevisionKilometraje.objects.filter(movimiento_especial=movimiento).count(), revisiones)

    def test_lote_mixto_con_punto_de_prefijo_verificado_da_400_sin_guardar_parcialmente(self):
        from apps.solicitudes.servicios_movimientos import confirmar_sincronizacion_movimiento

        movimiento = self.preparar_especial_finalizado()
        confirmar_sincronizacion_movimiento(self.usuario_repartidor, self.solicitud.pk, {"sesiones_gps": []})
        movimiento.refresh_from_db()
        cliente = APIClient()
        cliente.force_authenticate(self.usuario_repartidor)
        sesion = uuid4()
        registros = [
            {**self._registro(instante), "sesion_gps": str(sesion), "secuencia": indice + 1}
            for indice, instante in enumerate((movimiento.finalizada_en + timedelta(seconds=1), movimiento.iniciada_en))
        ]
        respuesta = cliente.post(reverse("seguimiento:registros"), {
            "jornada_id": str(self.jornada.pk), "registros": registros,
        }, format="json")
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("registrada_en", respuesta.data["registros"][1])
        self.assertEqual(RegistroUbicacion.objects.filter(jornada=self.jornada).count(), 0)

    def test_especial_verificado_permite_reintento_y_continuar_misma_sesion_despues(self):
        from apps.solicitudes.servicios_movimientos import confirmar_sincronizacion_movimiento

        movimiento = self.preparar_especial_finalizado()
        sesion = uuid4()
        punto = {**self._registro(movimiento.iniciada_en + timedelta(seconds=20)),
                 "sesion_gps": sesion, "secuencia": 1}
        registrar_ubicaciones(self.usuario_repartidor, {"jornada_id": self.jornada.pk, "registros": [punto]})
        confirmar_sincronizacion_movimiento(self.usuario_repartidor, self.solicitud.pk, {
            "sesiones_gps": [{"sesion_gps": sesion, "ultima_secuencia": 1}],
        })
        movimiento.refresh_from_db()
        calidad = dict(movimiento.calidad_kilometraje)
        cantidad = RevisionKilometraje.objects.filter(movimiento_especial=movimiento).count()
        lote_repetido = {"jornada_id": self.jornada.pk, "registros": [punto]}
        self.assertEqual(registrar_ubicaciones(self.usuario_repartidor, lote_repetido)["repetidos"], 1)
        siguiente = {**self._registro(movimiento.finalizada_en + timedelta(seconds=1)),
                     "sesion_gps": sesion, "secuencia": 2}
        resultado = registrar_ubicaciones(self.usuario_repartidor, {
            "jornada_id": self.jornada.pk, "registros": [punto, siguiente],
        })
        self.assertEqual((resultado["creados"], resultado["repetidos"]), (1, 1))
        self.assertIsNone(resultado["registros"][1].movimiento_envio_especial_id)
        movimiento.refresh_from_db()
        self.assertEqual(movimiento.calidad_kilometraje, calidad)
        self.assertEqual(RevisionKilometraje.objects.filter(movimiento_especial=movimiento).count(), cantidad)

    def test_especial_sin_verificar_sigue_admitiendo_gps_tardio(self):
        movimiento = self.preparar_especial_finalizado()
        punto = {**self._registro(movimiento.iniciada_en + timedelta(seconds=20)),
                 "sesion_gps": uuid4(), "secuencia": 1}
        resultado = registrar_ubicaciones(self.usuario_repartidor, {"jornada_id": self.jornada.pk, "registros": [punto]})
        self.assertEqual(resultado["creados"], 1)
        self.assertEqual(resultado["registros"][0].movimiento_envio_especial_id, movimiento.pk)

    def preparar_cierre(self, omitir=()):
        self.sesion = uuid4()
        inicio = self.ahora - timedelta(minutes=5)
        fin = inicio + timedelta(seconds=60)
        self.asignacion.estado = EstadoAsignacionSolicitud.FINALIZADA
        self.asignacion.finalizada_en = fin
        self.asignacion.save()
        self.solicitud.estado = EstadoSolicitud.ENTREGADA
        self.solicitud.entregada_en = fin
        self.solicitud.save()
        self.puntos = [
            {**self._registro(inicio + timedelta(seconds=(i - 1) * 5)),
             "sesion_gps": self.sesion, "secuencia": i,
             "latitud": Decimal("14.000000") + Decimal(i - 1) / Decimal("10000")}
            for i in range(1, 14)
        ]
        registrar_ubicaciones(self.usuario_repartidor, {
            "jornada_id": self.jornada.id,
            "registros": [p for p in self.puntos if p["secuencia"] not in omitir],
        })
        return {"sesiones_gps": [{"sesion_gps": self.sesion, "ultima_secuencia": 13}]}

    def test_cierre_pendiente_se_consolida_con_gps_tardio_sin_duplicar(self):
        datos = self.preparar_cierre(omitir=(7,))
        cerrada = finalizar_jornada(self.usuario_repartidor, self.jornada.id, datos)
        self.assertEqual(cerrada.estado, "FINALIZADA")
        self.assertEqual(cerrada.calidad_kilometraje["estado"], "PENDIENTE_SINCRONIZACION")
        self.assertEqual(cerrada.calidad_kilometraje["puntos_pendientes"], 1)
        lote = {"jornada_id": self.jornada.id, "registros": [self.puntos[6]]}
        registrar_ubicaciones(self.usuario_repartidor, lote)
        cerrada.refresh_from_db()
        self.assertEqual(cerrada.calidad_kilometraje["estado"], "CONSOLIDADO")
        self.assertEqual(cerrada.minutos_operativos, 1)
        self.assertGreaterEqual(cerrada.minutos_activos, 15)
        self.assertEqual(cerrada.calidad_kilometraje["cobertura_porcentaje"], 100)
        revisiones = RevisionKilometraje.objects.filter(jornada=cerrada).count()
        registrar_ubicaciones(self.usuario_repartidor, lote)
        self.assertEqual(RevisionKilometraje.objects.filter(jornada=cerrada).count(), revisiones)

    def test_cierre_no_verificado_admite_confirmacion_posterior(self):
        datos = self.preparar_cierre()
        cerrada = finalizar_jornada(self.usuario_repartidor, self.jornada.id, {})
        self.assertEqual(cerrada.calidad_kilometraje["estado"], "SIN_VERIFICAR")
        cliente = APIClient()
        cliente.force_authenticate(self.usuario_repartidor)
        respuesta = cliente.post(reverse("jornadas:sincronizacion-gps", args=[cerrada.id]), {
            "sesiones_gps": [{"sesion_gps": str(self.sesion), "ultima_secuencia": 13}],
        }, format="json")
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.data["calidad_kilometraje"]["sincronizacion_verificada"])
        with self.assertRaises(ValidationError):
            confirmar_sincronizacion_jornada(self.usuario_repartidor, cerrada.id, {"sesiones_gps": []})

    def test_ultimo_punto_recibido_no_oculta_huecos_intermedios(self):
        datos = self.preparar_cierre(omitir=(3, 8))
        cerrada = finalizar_jornada(self.usuario_repartidor, self.jornada.id, datos)
        self.assertEqual(cerrada.calidad_kilometraje["puntos_pendientes"], 2)

    def test_secuencia_no_puede_usarse_con_otro_uuid(self):
        self.preparar_cierre()
        conflictivo = {**self.puntos[0], "id_cliente": uuid4()}
        with self.assertRaises(ValidationError):
            registrar_ubicaciones(self.usuario_repartidor, {"jornada_id": self.jornada.id, "registros": [conflictivo]})

    def test_secuencia_sin_sesion_da_error_del_campo(self):
        entrada = SerializadorLoteRegistrosUbicacion(data={
            "jornada_id": str(self.jornada.id), "registros": [{**self._registro(self.ahora), "secuencia": 1}],
        })
        self.assertFalse(entrada.is_valid())
        self.assertIn("secuencia", entrada.errors["registros"][0])

    def test_confirmar_jornada_ajena_no_modifica_medicion(self):
        datos = self.preparar_cierre()
        cerrada = finalizar_jornada(self.usuario_repartidor, self.jornada.id, datos)
        cliente = APIClient()
        cliente.force_authenticate(self.solicitante)
        respuesta = cliente.post(reverse("jornadas:sincronizacion-gps", args=[cerrada.id]), {"sesiones_gps": []}, format="json")
        self.assertIn(respuesta.status_code, (403, 404))

    def test_configuracion_gps_es_autenticada_y_solo_para_motorista(self):
        cliente = APIClient()
        url = reverse("seguimiento:configuracion")
        self.assertEqual(cliente.get(url).status_code, 401)
        cliente.force_authenticate(self.usuario_repartidor)
        ahora = timezone.now()
        with patch("apps.seguimiento.selectores.timezone.now", return_value=ahora):
            respuesta = cliente.get(url, {"hora_servidor": "2000-01-01T00:00:00Z"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data["hora_servidor"], ahora.isoformat())
        self.assertEqual(respuesta.data["zona_horaria_operativa"], "America/Tegucigalpa")
        self.assertTrue(respuesta.data["asignacion_requiere_gps_vigente"])
        cliente.force_authenticate(self.solicitante)
        self.assertEqual(cliente.get(url).status_code, 404)

    def test_revisiones_paginadas_conservan_cierre_y_consolidacion(self):
        datos = self.preparar_cierre(omitir=(7,))
        finalizar_jornada(self.usuario_repartidor, self.jornada.id, datos)
        registrar_ubicaciones(self.usuario_repartidor, {"jornada_id": self.jornada.id, "registros": [self.puntos[6]]})
        cliente = APIClient()
        cliente.force_authenticate(self.usuario_repartidor)
        respuesta = cliente.get(reverse("jornadas:revisiones-kilometraje", args=[self.jornada.id]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data["conteo"], 2)

    def test_multiples_solicitudes_no_multiplican_kilometros_ni_tiempo(self):
        datos = self.preparar_cierre()
        from apps.jornadas.kilometraje import medir_jornada
        from apps.solicitudes.models import AsignacionSolicitud

        antes = medir_jornada(self.jornada, timezone.now())
        otra = Solicitud.objects.create(
            cantidad_tubos=1,
            numero="SOL-SUPERPUESTA", empresa=self.empresa, solicitada_por=self.solicitante,
            repartidor_asignado=self.repartidor, prioridad="NORMAL", tipo_servicio=self.tipo_servicio,
            origen=self.origen, destino=self.destino, estado=EstadoSolicitud.ENTREGADA,
        )
        AsignacionSolicitud.objects.create(
            solicitud=otra, repartidor=self.repartidor, asignada_por=self.administrador,
            estado=EstadoAsignacionSolicitud.FINALIZADA, aceptada_en=self.asignacion.aceptada_en,
            finalizada_en=self.asignacion.finalizada_en,
        )
        despues = medir_jornada(self.jornada, timezone.now())
        self.assertEqual(antes["kilometros"], despues["kilometros"])
        self.assertEqual(antes["segundos_operativos"], despues["segundos_operativos"])

    def test_especial_pendiente_recibe_gps_tardio_y_guarda_revision(self):
        from apps.solicitudes.servicios_movimientos import iniciar_movimiento_especial, cerrar_movimiento_especial

        self.solicitud.modalidad = "ESPECIAL"
        self.solicitud.destino = None
        self.solicitud.destino_especial = "Encargo de prueba"
        self.solicitud.save()
        inicio = self.ahora - timedelta(minutes=4)
        movimiento = iniciar_movimiento_especial(
            self.solicitud, self.repartidor, latitud=Decimal("14"), longitud=Decimal("-87"), ahora=inicio,
        )
        sesion = uuid4()
        puntos = [
            {**self._registro(inicio + timedelta(seconds=i * 10)), "sesion_gps": sesion,
             "secuencia": i, "latitud": Decimal("14") + Decimal(i) / 10000, "longitud": Decimal("-87")}
            for i in (1, 2, 3)
        ]
        registrar_ubicaciones(self.usuario_repartidor, {"jornada_id": self.jornada.id, "registros": [puntos[0], puntos[2]]})
        cerrado = cerrar_movimiento_especial(
            self.solicitud, self.repartidor, latitud=Decimal("14.0004"), longitud=Decimal("-87"),
            ahora=inicio + timedelta(seconds=40),
            sesiones_gps=[{"sesion_gps": sesion, "ultima_secuencia": 3}],
        )
        self.assertEqual(cerrado.calidad_kilometraje["estado"], "PENDIENTE_SINCRONIZACION")
        registrar_ubicaciones(self.usuario_repartidor, {"jornada_id": self.jornada.id, "registros": [puntos[1]]})
        cerrado.refresh_from_db()
        self.assertTrue(cerrado.calidad_kilometraje["sincronizacion_verificada"])
        self.assertEqual(cerrado.calidad_kilometraje["estado"], "INCOMPLETO")  # Extremos sin precisión.
        self.assertEqual(RevisionKilometraje.objects.filter(movimiento_especial=movimiento).count(), 2)
        # La consolidación automática también sella el prefijo, aunque su
        # calidad sea INCOMPLETO; reintentar lo recibido continúa permitido.
        repetido = registrar_ubicaciones(self.usuario_repartidor, {
            "jornada_id": self.jornada.id, "registros": [puntos[1]],
        })
        self.assertEqual(repetido["repetidos"], 1)
        inesperado = {**puntos[1], "id_cliente": uuid4(), "secuencia": 4}
        with self.assertRaises(ValidationError):
            registrar_ubicaciones(self.usuario_repartidor, {
                "jornada_id": self.jornada.id, "registros": [inesperado],
            })
        self.assertEqual(RevisionKilometraje.objects.filter(movimiento_especial=movimiento).count(), 2)

    def test_prioritario_recogido_bloquea_operacion_de_otra_solicitud(self):
        Solicitud.objects.create(
            cantidad_tubos=1,
            numero="PRIORIDAD-EXCLUSIVA", empresa=self.empresa, solicitada_por=self.solicitante,
            repartidor_asignado=self.repartidor, prioridad="PRIORITY", tipo_servicio=self.tipo_servicio,
            origen=self.origen, destino=self.destino, estado=EstadoSolicitud.RECOLECTADA,
        )
        with self.assertRaises(ValidationError):
            cambiar_estado_solicitud(self.usuario_repartidor, self.solicitud.id, {"estado_destino": EstadoSolicitud.EN_RECOLECCION})
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.HACIA_RECOLECCION)
