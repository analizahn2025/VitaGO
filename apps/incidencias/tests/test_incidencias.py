import tempfile
import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from apps.flota.models import Vehiculo
from apps.geografia.models import Pais
from apps.incidencias.models import (
    EventoIncidencia,
    EvidenciaIncidencia,
    Incidencia,
)
from apps.incidencias.opciones import EstadoIncidencia, TipoEventoIncidencia
from apps.incidencias.selectores import listar_incidencias_autorizadas
from apps.incidencias.servicios import (
    crear_incidencia,
    revisar_incidencia,
)
from apps.jornadas.models import JornadaRepartidor
from apps.jornadas.servicios import finalizar_jornada
from apps.organizaciones.models import Empresa
from apps.repartidores.models import Repartidor
from apps.repartidores.opciones import EstadoOperativoRepartidor
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
class PruebasIncidencias(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.directorio_temporal = tempfile.TemporaryDirectory()
        cls.ajuste_archivos = override_settings(
            MEDIA_ROOT=cls.directorio_temporal.name
        )
        cls.ajuste_archivos.enable()

    @classmethod
    def tearDownClass(cls):
        cls.ajuste_archivos.disable()
        cls.directorio_temporal.cleanup()
        super().tearDownClass()

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
        cls.otra_empresa = Empresa.objects.create(
            nombre="Otra empresa",
            pais=cls.pais,
        )
        cls.administrador = Usuario.objetos.create(
            correo="administrador.incidencias@analiza.test",
            nombres="Administrador",
            apellidos="Incidencias",
            empresa=cls.empresa,
            es_superusuario=True,
        )
        cls.gerente_operaciones = Usuario.objetos.create(
            correo="gerente.incidencias@analiza.test",
            nombres="Gerente",
            apellidos="Incidencias",
            empresa=cls.empresa,
        )
        RolUsuario.objetos.create(
            usuario=cls.gerente_operaciones,
            rol=Rol.objetos.get(codigo="GERENTE_OPERACIONES"),
            tipo_alcance=TipoAlcanceRol.EMPRESA,
            empresa=cls.empresa,
            asignado_por=cls.administrador,
        )
        cls.repartidores = []
        rol_repartidor = Rol.objetos.get(codigo="REPARTIDOR_CORPORATIVO")
        for indice, empresa in enumerate((cls.empresa, cls.otra_empresa), 1):
            usuario = Usuario.objetos.create(
                correo=f"motorista.incidencias{indice}@analiza.test",
                nombres=f"Motorista {indice}",
                apellidos="Incidencias",
                empresa=empresa,
            )
            RolUsuario.objetos.create(
                usuario=usuario,
                rol=rol_repartidor,
                tipo_alcance=TipoAlcanceRol.EMPRESA,
                empresa=empresa,
                asignado_por=cls.administrador,
            )
            vehiculo = Vehiculo.objects.create(
                empresa=empresa,
                placa=f"INC-{indice}",
                tipo="MOTOCICLETA",
            )
            cls.repartidores.append(
                Repartidor.objects.create(
                    usuario=usuario,
                    empresa=empresa,
                    vehiculo=vehiculo,
                    estado_operativo=EstadoOperativoRepartidor.DISPONIBLE,
                )
            )

        tipo_ubicacion = TipoUbicacion.objects.create(
            codigo="PRUEBA_INCIDENCIA",
            nombre="Prueba de incidencia",
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
            codigo="PRUEBA_INCIDENCIA",
            nombre="Prueba de incidencia",
        )

    @property
    def repartidor(self):
        return self.repartidores[0]

    def setUp(self):
        self.ahora = timezone.now()
        self.jornada = JornadaRepartidor.objects.create(
            repartidor=self.repartidor,
            iniciada_en=self.ahora - timedelta(minutes=30),
        )

    def _datos(self, **cambios):
        datos = {
            "descripcion": "Calle cerrada por trabajos.",
            "latitud": Decimal("14.075000"),
            "longitud": Decimal("-87.190000"),
            "reportada_en": self.ahora - timedelta(minutes=2),
        }
        datos.update(cambios)
        return datos

    def _crear_solicitud_asignada(self):
        solicitud = Solicitud.objects.create(
            numero=f"SOL-INC-{uuid.uuid4().hex[:8]}",
            empresa=self.empresa,
            solicitada_por=self.administrador,
            repartidor_asignado=self.repartidor,
            prioridad=PrioridadSolicitud.NORMAL,
            tipo_servicio=self.tipo_servicio,
            origen=self.origen,
            destino=self.destino,
            estado=EstadoSolicitud.HACIA_RECOLECCION,
            asignada_en=self.ahora - timedelta(minutes=10),
        )
        AsignacionSolicitud.objects.create(
            solicitud=solicitud,
            repartidor=self.repartidor,
            asignada_por=self.administrador,
            asignada_en=self.ahora - timedelta(minutes=10),
            aceptada_en=self.ahora - timedelta(minutes=9),
        )
        return solicitud

    def test_motorista_reporta_incidencia_y_genera_evento(self):
        incidencia = crear_incidencia(
            self.repartidor.usuario,
            self._datos(),
        )

        self.assertEqual(incidencia.jornada, self.jornada)
        self.assertEqual(incidencia.estado, EstadoIncidencia.ABIERTA)
        self.assertTrue(
            EventoIncidencia.objects.filter(
                incidencia=incidencia,
                tipo=TipoEventoIncidencia.REPORTADA,
            ).exists()
        )

    def test_solicitud_relacionada_debe_pertenecer_al_motorista(self):
        solicitud = Solicitud.objects.create(
            numero=f"SOL-AJENA-{uuid.uuid4().hex[:8]}",
            empresa=self.empresa,
            solicitada_por=self.administrador,
            prioridad=PrioridadSolicitud.NORMAL,
            tipo_servicio=self.tipo_servicio,
            origen=self.origen,
            destino=self.destino,
            estado=EstadoSolicitud.PENDIENTE,
        )

        with self.assertRaises(ValidationError):
            crear_incidencia(
                self.repartidor.usuario,
                self._datos(solicitud_id=solicitud.id),
            )

    def test_acepta_solicitud_asignada_en_el_momento_reportado(self):
        solicitud = self._crear_solicitud_asignada()

        incidencia = crear_incidencia(
            self.repartidor.usuario,
            self._datos(solicitud_id=solicitud.id),
        )

        self.assertEqual(incidencia.solicitud, solicitud)

    def test_motorista_solo_lista_sus_incidencias(self):
        propia = crear_incidencia(self.repartidor.usuario, self._datos())
        jornada_ajena = JornadaRepartidor.objects.create(
            repartidor=self.repartidores[1],
            iniciada_en=self.ahora - timedelta(minutes=20),
        )
        Incidencia.objects.create(
            jornada=jornada_ajena,
            repartidor=self.repartidores[1],
            descripcion="Incidencia ajena",
            reportada_en=self.ahora - timedelta(minutes=1),
        )

        resultados = listar_incidencias_autorizadas(self.repartidor.usuario)

        self.assertTrue(resultados.filter(id=propia.id).exists())
        self.assertEqual(resultados.count(), 1)

    def test_gerente_solo_lista_incidencias_de_su_empresa(self):
        propia = crear_incidencia(self.repartidor.usuario, self._datos())
        jornada_ajena = JornadaRepartidor.objects.create(
            repartidor=self.repartidores[1],
            iniciada_en=self.ahora - timedelta(minutes=20),
        )
        Incidencia.objects.create(
            jornada=jornada_ajena,
            repartidor=self.repartidores[1],
            descripcion="Incidencia de otra empresa",
            reportada_en=self.ahora - timedelta(minutes=1),
        )

        resultados = listar_incidencias_autorizadas(self.gerente_operaciones)

        self.assertTrue(resultados.filter(id=propia.id).exists())
        self.assertEqual(resultados.count(), 1)

    def test_revision_conserva_eventos_y_respeta_transiciones(self):
        incidencia = crear_incidencia(self.repartidor.usuario, self._datos())

        en_revision = revisar_incidencia(
            self.gerente_operaciones,
            incidencia.id,
            {"estado": EstadoIncidencia.EN_REVISION, "notas": "Validando."},
        )
        cerrada = revisar_incidencia(
            self.gerente_operaciones,
            incidencia.id,
            {"estado": EstadoIncidencia.CERRADA, "notas": "Resuelta."},
        )

        self.assertEqual(en_revision.estado, EstadoIncidencia.EN_REVISION)
        self.assertEqual(cerrada.estado, EstadoIncidencia.CERRADA)
        self.assertIsNotNone(cerrada.cerrada_en)
        self.assertEqual(cerrada.eventos.count(), 3)
        with self.assertRaises(ValidationError):
            revisar_incidencia(
                self.gerente_operaciones,
                incidencia.id,
                {"estado": EstadoIncidencia.EN_REVISION},
            )

    def test_motorista_no_puede_revisar_incidencia(self):
        incidencia = crear_incidencia(self.repartidor.usuario, self._datos())

        with self.assertRaises(PermissionDenied):
            revisar_incidencia(
                self.repartidor.usuario,
                incidencia.id,
                {"estado": EstadoIncidencia.CERRADA},
            )

    def test_api_registra_y_descarga_evidencia_privada(self):
        incidencia = crear_incidencia(self.repartidor.usuario, self._datos())
        cliente = APIClient()
        cliente.force_authenticate(self.repartidor.usuario)
        imagen = SimpleUploadedFile(
            "incidencia.png",
            b"\x89PNG\r\n\x1a\n" + b"contenido-prueba",
            content_type="image/png",
        )

        respuesta = cliente.post(
            reverse(
                "incidencias:evidencias",
                kwargs={"incidencia_id": incidencia.id},
            ),
            {
                "archivo": imagen,
                "latitud": "14.075000",
                "longitud": "-87.190000",
                "capturada_en": (
                    self.ahora - timedelta(minutes=1)
                ).isoformat(),
            },
            format="multipart",
        )

        self.assertEqual(respuesta.status_code, 201)
        evidencia = EvidenciaIncidencia.objects.get()
        respuesta_archivo = cliente.get(
            reverse(
                "incidencias:archivo-evidencia",
                kwargs={
                    "incidencia_id": incidencia.id,
                    "evidencia_id": evidencia.id,
                },
            )
        )
        self.assertEqual(respuesta_archivo.status_code, 200)
        self.assertEqual(respuesta_archivo["Cache-Control"], "private, no-store")
        respuesta_archivo.close()

    def test_finalizar_jornada_congela_cantidad_de_incidencias(self):
        crear_incidencia(self.repartidor.usuario, self._datos())

        jornada = finalizar_jornada(
            self.repartidor.usuario,
            self.jornada.id,
            {},
        )

        self.assertEqual(jornada.incidencias_reportadas, 1)

    def test_api_creacion_listado_detalle_y_revision(self):
        cliente = APIClient()
        cliente.force_authenticate(self.repartidor.usuario)
        respuesta_creacion = cliente.post(
            reverse("incidencias:lista-creacion"),
            {
                "descripcion": "Problema mecánico.",
                "reportada_en": (
                    self.ahora - timedelta(minutes=1)
                ).isoformat(),
            },
            format="json",
        )
        incidencia_id = respuesta_creacion.data["id"]
        respuesta_lista = cliente.get(reverse("incidencias:lista-creacion"))
        respuesta_detalle = cliente.get(
            reverse(
                "incidencias:detalle",
                kwargs={"incidencia_id": incidencia_id},
            )
        )

        cliente.force_authenticate(self.gerente_operaciones)
        respuesta_revision = cliente.post(
            reverse(
                "incidencias:revision",
                kwargs={"incidencia_id": incidencia_id},
            ),
            {"estado": EstadoIncidencia.CERRADA, "notas": "Atendida."},
            format="json",
        )

        self.assertEqual(respuesta_creacion.status_code, 201)
        self.assertEqual(respuesta_lista.status_code, 200)
        self.assertEqual(respuesta_lista.data["conteo"], 1)
        self.assertEqual(respuesta_detalle.status_code, 200)
        self.assertEqual(respuesta_revision.status_code, 200)
        self.assertEqual(
            respuesta_revision.data["estado"],
            EstadoIncidencia.CERRADA,
        )
