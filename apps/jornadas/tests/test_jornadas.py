from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.flota.models import Vehiculo
from apps.geografia.models import Pais
from apps.jornadas.models import JornadaRepartidor
from apps.jornadas.opciones import EstadoJornada
from apps.jornadas.selectores import listar_jornadas_autorizadas
from apps.jornadas.servicios import _calcular_resumen, finalizar_jornada, iniciar_jornada
from apps.seguimiento.models import RegistroUbicacion
from apps.organizaciones.models import Empresa
from apps.repartidores.models import HistorialEstadoRepartidor, Repartidor
from apps.repartidores.opciones import (
    CapacidadRepartidor,
    EstadoOperativoRepartidor,
)
from apps.solicitudes.models import (
    AsignacionSolicitud,
    MovimientoEnvioEspecial,
    Solicitud,
    TipoServicio,
)
from apps.solicitudes.opciones import (
    EstadoAsignacionSolicitud,
    EstadoMovimientoEnvioEspecial,
    EstadoSolicitud,
    ModalidadSolicitud,
    PrioridadSolicitud,
)
from apps.ubicaciones.models import TipoUbicacion, Ubicacion
from apps.ubicaciones.opciones import OrigenUbicacion
from apps.usuarios.models import Rol, RolUsuario, Usuario
from apps.usuarios.opciones import TipoAlcanceRol


@override_settings(
    MODO_APLICACION="CORPORATIVO",
    PROVEEDOR_AUTENTICACION="LOCAL",
)
class PruebasJornadas(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pais = Pais.objects.create(
            iso2="HN",
            iso3="HND",
            nombre="Honduras",
            codigo_telefonico="+504",
            codigo_moneda="HNL",
            zona_horaria_predeterminada="America/Tegucigalpa",
        )
        cls.empresa = Empresa.objects.create(nombre="Analiza", pais=cls.pais)
        tipo_ubicacion = TipoUbicacion.objects.create(
            codigo="PRUEBA_JORNADA",
            nombre="Prueba de jornada",
        )
        cls.origen = Ubicacion.objects.create(
            nombre="Origen",
            tipo_ubicacion=tipo_ubicacion,
            origen=OrigenUbicacion.REGISTRADA_USUARIO,
            pais=cls.pais,
            direccion="Origen de prueba",
            latitud=Decimal("14.072300"),
            longitud=Decimal("-87.192100"),
        )
        cls.destino = Ubicacion.objects.create(
            nombre="Destino",
            tipo_ubicacion=tipo_ubicacion,
            origen=OrigenUbicacion.REGISTRADA_USUARIO,
            pais=cls.pais,
            direccion="Destino de prueba",
            latitud=Decimal("14.082300"),
            longitud=Decimal("-87.182100"),
        )
        cls.tipo_servicio = TipoServicio.objects.create(
            codigo="PRUEBA_JORNADA",
            nombre="Prueba de jornada",
        )
        cls.administrador = Usuario.objetos.create(
            correo="administrador.jornada@analiza.test",
            nombres="Administrador",
            apellidos="Jornada",
            empresa=cls.empresa,
            es_superusuario=True,
        )
        rol_repartidor = Rol.objetos.get(codigo="REPARTIDOR_CORPORATIVO")
        cls.repartidores = []
        for indice in (1, 2):
            usuario = Usuario.objetos.create(
                correo=f"motorista.jornada{indice}@analiza.test",
                nombres=f"Motorista {indice}",
                apellidos="Jornada",
                empresa=cls.empresa,
            )
            RolUsuario.objetos.create(
                usuario=usuario,
                rol=rol_repartidor,
                tipo_alcance=TipoAlcanceRol.EMPRESA,
                empresa=cls.empresa,
                asignado_por=cls.administrador,
            )
            vehiculo = Vehiculo.objects.create(
                empresa=cls.empresa,
                placa=f"JOR-{indice}",
                tipo="MOTOCICLETA",
            )
            cls.repartidores.append(
                Repartidor.objects.create(
                    usuario=usuario,
                    empresa=cls.empresa,
                    vehiculo=vehiculo,
                    estado_operativo=EstadoOperativoRepartidor.DESCONECTADO,
                )
            )

    @property
    def repartidor(self):
        return self.repartidores[0]

    def _iniciar(self):
        return iniciar_jornada(
            self.repartidor.usuario,
            {
                "latitud": Decimal("14.072300"),
                "longitud": Decimal("-87.192100"),
            },
        )

    def _crear_solicitud_entregada(self, numero, prioridad):
        ahora = timezone.now()
        return Solicitud.objects.create(
            cantidad_tubos=1,
            numero=numero,
            empresa=self.empresa,
            solicitada_por=self.administrador,
            repartidor_asignado=self.repartidor,
            prioridad=prioridad,
            tipo_servicio=self.tipo_servicio,
            origen=self.origen,
            destino=self.destino,
            estado=EstadoSolicitud.ENTREGADA,
            recolectada_en=ahora,
            entregada_en=ahora,
        )

    def _iniciar_hace_una_hora(self):
        jornada = self._iniciar()
        JornadaRepartidor.objects.filter(pk=jornada.pk).update(
            iniciada_en=timezone.now() - timedelta(hours=1)
        )
        jornada.refresh_from_db()
        return jornada

    def _crear_asignacion_finalizada(self, jornada, numero, inicio, fin):
        solicitud = self._crear_solicitud_entregada(
            numero, PrioridadSolicitud.NORMAL
        )
        AsignacionSolicitud.objects.create(
            solicitud=solicitud,
            repartidor=self.repartidor,
            asignada_por=self.administrador,
            estado=EstadoAsignacionSolicitud.FINALIZADA,
            asignada_en=inicio,
            aceptada_en=inicio,
            finalizada_en=fin,
        )
        return solicitud

    def _registrar_punto(
        self,
        jornada,
        minuto,
        latitud,
        *,
        operativo=True,
        precision=None,
        velocidad=None,
    ):
        return RegistroUbicacion.objects.create(
            id_cliente=uuid4(),
            repartidor=self.repartidor,
            jornada=jornada,
            registrada_en=jornada.iniciada_en + timedelta(minutes=minuto),
            latitud=Decimal(str(latitud)),
            longitud=Decimal("-87.192100"),
            es_operativo=operativo,
            precision_metros=precision,
            velocidad_metros_segundo=velocidad,
        )

    def test_iniciar_crea_jornada_y_habilita_motorista(self):
        jornada = self._iniciar()

        self.repartidor.refresh_from_db()
        self.assertEqual(jornada.estado, EstadoJornada.ACTIVA)
        self.assertEqual(
            self.repartidor.estado_operativo,
            EstadoOperativoRepartidor.DISPONIBLE,
        )
        self.assertTrue(
            HistorialEstadoRepartidor.objects.filter(
                repartidor=self.repartidor,
                estado_nuevo=EstadoOperativoRepartidor.DISPONIBLE,
            ).exists()
        )

    def test_inicio_de_jornada_reintenta_solicitud_pendiente(self):
        pendiente = Solicitud.objects.create(
            cantidad_tubos=1,
            numero="SOL-PENDIENTE-INICIO-JORNADA",
            empresa=self.empresa,
            solicitada_por=self.administrador,
            prioridad=PrioridadSolicitud.NORMAL,
            tipo_servicio=self.tipo_servicio,
            origen=self.origen,
            destino=self.destino,
        )

        with self.captureOnCommitCallbacks(execute=True):
            jornada = self._iniciar()
            from apps.seguimiento.servicios import registrar_ubicaciones

            registrar_ubicaciones(self.repartidor.usuario, {
                "jornada_id": jornada.id,
                "registros": [{"id_cliente": uuid4(), "latitud": self.origen.latitud,
                               "longitud": self.origen.longitud, "precision_metros": Decimal("8"),
                               "registrada_en": timezone.now()}],
            })

        pendiente.refresh_from_db()
        self.assertEqual(pendiente.estado, EstadoSolicitud.HACIA_RECOLECCION)
        self.assertEqual(pendiente.repartidor_asignado_id, self.repartidor.id)
        self.assertEqual(
            AsignacionSolicitud.objects.filter(solicitud=pendiente).count(), 1
        )

    def test_rechaza_dos_jornadas_activas(self):
        self._iniciar()

        with self.assertRaises(ValidationError):
            self._iniciar()

        self.assertEqual(
            JornadaRepartidor.objects.filter(
                repartidor=self.repartidor,
                estado=EstadoJornada.ACTIVA,
            ).count(),
            1,
        )

    def test_servicio_rechaza_coordenadas_incompletas(self):
        with self.assertRaises(ValidationError):
            iniciar_jornada(
                self.repartidor.usuario,
                {"latitud": Decimal("14.072300")},
            )

    def test_no_finaliza_con_asignacion_activa(self):
        jornada = self._iniciar()
        solicitud = Solicitud.objects.create(
            cantidad_tubos=1,
            numero="SOL-JORNADA-ACTIVA",
            empresa=self.empresa,
            solicitada_por=self.administrador,
            repartidor_asignado=self.repartidor,
            prioridad=PrioridadSolicitud.NORMAL,
            tipo_servicio=self.tipo_servicio,
            origen=self.origen,
            destino=self.destino,
            estado=EstadoSolicitud.ASIGNADA,
        )
        AsignacionSolicitud.objects.create(
            solicitud=solicitud,
            repartidor=self.repartidor,
            asignada_por=self.administrador,
        )

        with self.assertRaises(ValidationError):
            finalizar_jornada(self.repartidor.usuario, jornada.id, {})

        jornada.refresh_from_db()
        self.assertEqual(jornada.estado, EstadoJornada.ACTIVA)

    def test_finalizar_congela_resumen_y_desconecta_motorista(self):
        jornada = self._iniciar()
        self._crear_solicitud_entregada(
            "SOL-JORNADA-NORMAL",
            PrioridadSolicitud.NORMAL,
        )
        self._crear_solicitud_entregada(
            "SOL-JORNADA-PRIORITARIA",
            PrioridadSolicitud.PRIORITARIA,
        )

        finalizada = finalizar_jornada(
            self.repartidor.usuario,
            jornada.id,
            {
                "latitud": Decimal("14.082300"),
                "longitud": Decimal("-87.182100"),
            },
        )

        self.repartidor.refresh_from_db()
        self.assertEqual(finalizada.estado, EstadoJornada.FINALIZADA)
        self.assertIsNotNone(finalizada.finalizada_en)
        self.assertEqual(finalizada.servicios_completados, 2)
        self.assertEqual(finalizada.recolecciones_completadas, 2)
        self.assertEqual(finalizada.entregas_completadas, 2)
        self.assertEqual(finalizada.servicios_normales, 1)
        self.assertEqual(finalizada.servicios_prioritarios, 1)
        self.assertEqual(finalizada.kilometros_operativos, Decimal("0"))
        self.assertFalse(finalizada.kilometraje_disponible)
        self.assertEqual(
            self.repartidor.estado_operativo,
            EstadoOperativoRepartidor.DESCONECTADO,
        )
        self.assertEqual(self.repartidor.capacidad, CapacidadRepartidor.VACIO)

    def test_resumen_cuenta_entregas_con_cierre_exacto_normal_y_prioritario(self):
        jornada = self._iniciar_hace_una_hora()
        entrega = timezone.now() - timedelta(seconds=1)
        for prioridad in (PrioridadSolicitud.NORMAL, PrioridadSolicitud.PRIORITARIA):
            solicitud = self._crear_solicitud_entregada(f"CIERRE-EXACTO-{prioridad}", prioridad)
            solicitud.recolectada_en = entrega - timedelta(minutes=1)
            solicitud.entregada_en = entrega
            solicitud.save()
            AsignacionSolicitud.objects.create(
                solicitud=solicitud, repartidor=self.repartidor,
                asignada_por=self.administrador,
                estado=EstadoAsignacionSolicitud.FINALIZADA,
                asignada_en=jornada.iniciada_en, finalizada_en=entrega,
            )
        resumen = _calcular_resumen(jornada, entrega)
        self.assertEqual(
            tuple(resumen[campo] for campo in (
                "servicios_completados", "entregas_completadas",
                "recolecciones_completadas", "servicios_normales", "servicios_prioritarios",
            )),
            (2, 2, 2, 1, 1),
        )

    def test_inicio_y_cierre_usan_reloj_servidor_no_fechas_del_cliente(self):
        cliente = APIClient()
        cliente.force_authenticate(self.repartidor.usuario)
        antes = timezone.now()
        manipuladas = {"iniciada_en": (antes - timedelta(days=3650)).isoformat(),
                       "finalizada_en": (antes + timedelta(days=3650)).isoformat()}
        inicio = cliente.post(reverse("jornadas:iniciar"), manipuladas, format="json")
        self.assertEqual(inicio.status_code, 201, inicio.data)
        jornada = JornadaRepartidor.objects.get(pk=inicio.data["id"])
        self.assertGreaterEqual(jornada.iniciada_en, antes)
        self.assertLessEqual(jornada.iniciada_en, timezone.now())
        iniciada_en = jornada.iniciada_en
        antes_cierre = timezone.now()
        cierre = cliente.post(reverse("jornadas:finalizar", args=[jornada.pk]), manipuladas, format="json")
        self.assertEqual(cierre.status_code, 200, cierre.data)
        jornada.refresh_from_db()
        self.assertEqual(jornada.iniciada_en, iniciada_en)
        self.assertGreaterEqual(jornada.finalizada_en, antes_cierre)
        self.assertLessEqual(jornada.finalizada_en, timezone.now())

    def test_cierre_exacto_no_atribuye_entrega_a_asignacion_cancelada_o_reasignada(self):
        original = self._iniciar_hace_una_hora()
        reemplazo = JornadaRepartidor.objects.create(
            repartidor=self.repartidores[1], iniciada_en=original.iniciada_en,
        )
        entrega = timezone.now() - timedelta(seconds=1)
        for estado in (EstadoAsignacionSolicitud.CANCELADA, EstadoAsignacionSolicitud.REASIGNADA):
            solicitud = self._crear_solicitud_entregada(f"CIERRE-LIMITE-{estado}", PrioridadSolicitud.NORMAL)
            solicitud.repartidor_asignado = self.repartidores[1]
            solicitud.recolectada_en = entrega - timedelta(minutes=1)
            solicitud.entregada_en = entrega
            solicitud.save()
            AsignacionSolicitud.objects.create(
                solicitud=solicitud, repartidor=self.repartidor,
                asignada_por=self.administrador, estado=estado,
                asignada_en=original.iniciada_en, finalizada_en=entrega,
            )
            AsignacionSolicitud.objects.create(
                solicitud=solicitud, repartidor=self.repartidores[1],
                asignada_por=self.administrador, estado=EstadoAsignacionSolicitud.FINALIZADA,
                asignada_en=entrega, finalizada_en=entrega,
            )
        anterior = _calcular_resumen(original, entrega)
        nuevo = _calcular_resumen(reemplazo, entrega)
        self.assertEqual((anterior["recolecciones_completadas"], anterior["entregas_completadas"]), (2, 0))
        self.assertEqual((nuevo["recolecciones_completadas"], nuevo["entregas_completadas"]), (0, 2))

    def test_kilometraje_cuenta_solo_puntos_operativos_en_asignacion(self):
        jornada = self._iniciar_hace_una_hora()
        inicio = jornada.iniciada_en + timedelta(minutes=10)
        fin = jornada.iniciada_en + timedelta(minutes=40)
        self._crear_asignacion_finalizada(
            jornada, "SOL-JORNADA-GPS", inicio, fin
        )
        self._registrar_punto(jornada, 5, "14.050000")
        self._registrar_punto(jornada, 12, "14.072300")
        self._registrar_punto(jornada, 22, "14.073300")
        self._registrar_punto(jornada, 22 + 5 / 60, "14.074300")
        self._registrar_punto(jornada, 25, "14.090000", operativo=False)
        self._registrar_punto(jornada, 45, "14.100000")

        finalizada = finalizar_jornada(self.repartidor.usuario, jornada.id, {})

        self.assertTrue(finalizada.kilometraje_disponible)
        self.assertGreater(finalizada.kilometros_operativos, Decimal("0.100"))
        self.assertLess(finalizada.kilometros_operativos, Decimal("0.120"))
        cliente = APIClient()
        cliente.force_authenticate(user=self.repartidor.usuario)
        respuesta = cliente.get(reverse("jornadas:detalle", args=[jornada.id]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.data["kilometraje_disponible"])
        self.assertEqual(
            Decimal(respuesta.data["kilometros_operativos"]),
            finalizada.kilometros_operativos,
        )

    def test_kilometraje_no_une_asignaciones_ni_saltos_invalidos(self):
        jornada = self._iniciar_hace_una_hora()
        base = jornada.iniciada_en
        self._crear_asignacion_finalizada(
            jornada, "SOL-JORNADA-TRAMO-1",
            base + timedelta(minutes=5), base + timedelta(minutes=20),
        )
        self._crear_asignacion_finalizada(
            jornada, "SOL-JORNADA-TRAMO-2",
            base + timedelta(minutes=30), base + timedelta(minutes=50),
        )
        self._registrar_punto(jornada, 10, "14.072300")
        self._registrar_punto(jornada, 15, "14.073300")
        self._registrar_punto(jornada, 15 + 5 / 60, "14.074300")
        self._registrar_punto(jornada, 32, "14.080000")
        self._registrar_punto(jornada, 34, "14.100000", precision=Decimal("101"))
        self._registrar_punto(jornada, 36, "14.081000")
        self._registrar_punto(jornada, 38, "14.090000", velocidad=Decimal("56"))
        self._registrar_punto(jornada, 39, "14.081500")
        self._registrar_punto(jornada, 40, "14.200000")  # salto > 55 m/s

        finalizada = finalizar_jornada(self.repartidor.usuario, jornada.id, {})

        self.assertTrue(finalizada.kilometraje_disponible)
        self.assertGreater(finalizada.kilometros_operativos, Decimal("0.100"))
        self.assertLess(finalizada.kilometros_operativos, Decimal("0.120"))

    def test_envio_especial_se_suma_una_vez_y_cierre_permanece_congelado(self):
        jornada = self._iniciar_hace_una_hora()
        inicio = jornada.iniciada_en + timedelta(minutes=10)
        fin = jornada.iniciada_en + timedelta(minutes=30)
        solicitud = Solicitud.objects.create(
            cantidad_tubos=1,
            numero="SOL-JORNADA-ESPECIAL",
            empresa=self.empresa,
            solicitada_por=self.administrador,
            repartidor_asignado=self.repartidor,
            prioridad=PrioridadSolicitud.NORMAL,
            modalidad=ModalidadSolicitud.ESPECIAL,
            tipo_servicio=self.tipo_servicio,
            origen=self.origen,
            destino_especial="Destino de prueba",
            estado=EstadoSolicitud.ENTREGADA,
            recolectada_en=fin,
            entregada_en=fin,
        )
        AsignacionSolicitud.objects.create(
            solicitud=solicitud,
            repartidor=self.repartidor,
            asignada_por=self.administrador,
            estado=EstadoAsignacionSolicitud.FINALIZADA,
            asignada_en=inicio,
            aceptada_en=inicio,
            finalizada_en=fin,
        )
        movimiento = MovimientoEnvioEspecial.objects.create(
            solicitud=solicitud,
            repartidor=self.repartidor,
            jornada=jornada,
            estado=EstadoMovimientoEnvioEspecial.FINALIZADO,
            iniciada_en=inicio,
            finalizada_en=fin,
            latitud_inicio=Decimal("14.072300"),
            longitud_inicio=Decimal("-87.192100"),
            latitud_fin=Decimal("14.080000"),
            longitud_fin=Decimal("-87.192100"),
            kilometros_recorridos=Decimal("1.500"),
        )
        RegistroUbicacion.objects.create(
            id_cliente=uuid4(), repartidor=self.repartidor, jornada=jornada,
            movimiento_envio_especial=movimiento, es_operativo=True,
            registrada_en=inicio + timedelta(minutes=5),
            latitud=Decimal("14.073300"), longitud=Decimal("-87.192100"),
        )
        self._registrar_punto(jornada, 20, "14.074300")
        self._registrar_punto(jornada, 25, "14.075300")
        self._registrar_punto(jornada, 35, "14.074300")

        finalizada = finalizar_jornada(self.repartidor.usuario, jornada.id, {})
        self.assertTrue(finalizada.kilometraje_disponible)
        self.assertEqual(finalizada.kilometros_operativos, Decimal("1.500"))

        self._registrar_punto(jornada, 37, "14.075300")
        finalizada.refresh_from_db()
        self.assertEqual(finalizada.kilometros_operativos, Decimal("1.500"))

    def test_motorista_solo_lista_sus_jornadas(self):
        propia = self._iniciar()
        ajena = JornadaRepartidor.objects.create(
            repartidor=self.repartidores[1],
        )

        jornadas = listar_jornadas_autorizadas(self.repartidor.usuario)

        self.assertTrue(jornadas.filter(pk=propia.pk).exists())
        self.assertFalse(jornadas.filter(pk=ajena.pk).exists())

    def test_endpoint_activa_devuelve_jornada_o_nulo(self):
        cliente = APIClient()
        cliente.force_authenticate(user=self.repartidor.usuario)
        respuesta_sin_jornada = cliente.get(reverse("jornadas:activa"))
        self.assertEqual(respuesta_sin_jornada.status_code, 200)
        self.assertIsNone(respuesta_sin_jornada.data["jornada"])

        jornada = self._iniciar()
        respuesta_con_jornada = cliente.get(reverse("jornadas:activa"))
        self.assertEqual(respuesta_con_jornada.status_code, 200)
        self.assertEqual(
            respuesta_con_jornada.data["jornada"]["id"],
            str(jornada.id),
        )
