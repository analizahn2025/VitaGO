from decimal import Decimal

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
from apps.jornadas.servicios import finalizar_jornada, iniciar_jornada
from apps.organizaciones.models import Empresa
from apps.repartidores.models import HistorialEstadoRepartidor, Repartidor
from apps.repartidores.opciones import (
    CapacidadRepartidor,
    EstadoOperativoRepartidor,
)
from apps.solicitudes.models import AsignacionSolicitud, Solicitud, TipoServicio
from apps.solicitudes.opciones import EstadoSolicitud, PrioridadSolicitud
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
            numero="SOL-PENDIENTE-INICIO-JORNADA",
            empresa=self.empresa,
            solicitada_por=self.administrador,
            prioridad=PrioridadSolicitud.NORMAL,
            tipo_servicio=self.tipo_servicio,
            origen=self.origen,
            destino=self.destino,
        )

        with self.captureOnCommitCallbacks(execute=True):
            self._iniciar()

        pendiente.refresh_from_db()
        self.assertEqual(pendiente.estado, EstadoSolicitud.ASIGNADA)
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
        self.assertEqual(
            self.repartidor.estado_operativo,
            EstadoOperativoRepartidor.DESCONECTADO,
        )
        self.assertEqual(self.repartidor.capacidad, CapacidadRepartidor.VACIO)

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
