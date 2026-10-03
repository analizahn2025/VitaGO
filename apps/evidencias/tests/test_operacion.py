import tempfile
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from apps.evidencias.models import EvidenciaSolicitud
from apps.evidencias.opciones import TipoEvidenciaSolicitud
from apps.evidencias.servicios import registrar_evidencia
from apps.flota.models import Vehiculo
from apps.geografia.models import Pais
from apps.organizaciones.models import Empresa
from apps.repartidores.models import Repartidor
from apps.repartidores.opciones import (
    CapacidadRepartidor,
    EstadoOperativoRepartidor,
)
from apps.solicitudes.models import (
    AsignacionSolicitud,
    EventoSolicitud,
    Solicitud,
    TipoServicio,
)
from apps.solicitudes.opciones import (
    EstadoAsignacionSolicitud,
    EstadoSolicitud,
    TipoEventoSolicitud,
)
from apps.solicitudes.servicios import cambiar_estado_solicitud
from apps.ubicaciones.models import TipoUbicacion, Ubicacion
from apps.ubicaciones.opciones import OrigenUbicacion
from apps.usuarios.models import Rol, RolUsuario, Usuario
from apps.usuarios.opciones import TipoAlcanceRol


@override_settings(
    MODO_APLICACION="CORPORATIVO",
    PROVEEDOR_AUTENTICACION="LOCAL",
    TAMANO_MAXIMO_EVIDENCIA_MB=10,
)
class PruebasOperacionConEvidencias(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directorio_temporal = tempfile.TemporaryDirectory()
        cls.cambio_almacenamiento = override_settings(
            MEDIA_ROOT=cls.directorio_temporal.name
        )
        cls.cambio_almacenamiento.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.cambio_almacenamiento.disable()
        cls.directorio_temporal.cleanup()

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
            codigo="PRUEBA_EVIDENCIA",
            nombre="Prueba de evidencia",
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
            codigo="PRUEBA_EVIDENCIA",
            nombre="Prueba de evidencia",
        )
        cls.administrador = Usuario.objetos.create(
            correo="administrador.evidencia@analiza.test",
            nombres="Administrador",
            apellidos="Evidencia",
            empresa=cls.empresa,
            es_superusuario=True,
        )
        cls.usuario_repartidor = Usuario.objetos.create(
            correo="motorista.evidencia@analiza.test",
            nombres="Motorista",
            apellidos="Evidencia",
            empresa=cls.empresa,
        )
        RolUsuario.objetos.create(
            usuario=cls.usuario_repartidor,
            rol=Rol.objetos.get(codigo="REPARTIDOR_CORPORATIVO"),
            tipo_alcance=TipoAlcanceRol.EMPRESA,
            empresa=cls.empresa,
            asignado_por=cls.administrador,
        )
        vehiculo = Vehiculo.objects.create(
            empresa=cls.empresa,
            placa="EVI-001",
            tipo="MOTOCICLETA",
        )
        cls.repartidor = Repartidor.objects.create(
            usuario=cls.usuario_repartidor,
            empresa=cls.empresa,
            vehiculo=vehiculo,
            estado_operativo=EstadoOperativoRepartidor.DISPONIBLE,
        )

    def setUp(self):
        self.solicitud = Solicitud.objects.create(
            numero=f"SOL-EVIDENCIA-{Solicitud.objects.count() + 1}",
            empresa=self.empresa,
            solicitada_por=self.administrador,
            repartidor_asignado=self.repartidor,
            prioridad="NORMAL",
            tipo_servicio=self.tipo_servicio,
            origen=self.origen,
            destino=self.destino,
            estado=EstadoSolicitud.ASIGNADA,
            asignada_en=timezone.now(),
        )
        AsignacionSolicitud.objects.create(
            solicitud=self.solicitud,
            repartidor=self.repartidor,
            asignada_por=self.administrador,
        )

    def _archivo_png(self, nombre="evidencia.png"):
        return SimpleUploadedFile(
            nombre,
            b"\x89PNG\r\n\x1a\n" + (b"\x00" * 32),
            content_type="image/png",
        )

    def _registrar(self, tipo):
        return registrar_evidencia(
            self.usuario_repartidor,
            self.solicitud.id,
            {
                "tipo": tipo,
                "archivo": self._archivo_png(),
                "latitud": Decimal("14.072300"),
                "longitud": Decimal("-87.192100"),
                "capturada_en": timezone.now(),
                "notas": "Evidencia de prueba",
            },
        )

    def _transicion(self, estado_destino):
        solicitud = cambiar_estado_solicitud(
            self.usuario_repartidor,
            self.solicitud.id,
            {
                "estado_destino": estado_destino,
                "latitud": Decimal("14.072300"),
                "longitud": Decimal("-87.192100"),
            },
        )
        self.solicitud = solicitud
        return solicitud

    def test_rechaza_evidencia_fuera_del_estado_permitido(self):
        with self.assertRaises(ValidationError):
            self._registrar(TipoEvidenciaSolicitud.FOTO_RECOLECCION)

        self.assertFalse(EvidenciaSolicitud.objects.exists())

    def test_solo_motorista_asignado_puede_registrar_evidencia(self):
        self.solicitud.estado = EstadoSolicitud.EN_RECOLECCION
        self.solicitud.save(update_fields=("estado", "actualizado_en"))

        with self.assertRaises(PermissionDenied):
            registrar_evidencia(
                self.administrador,
                self.solicitud.id,
                {
                    "tipo": TipoEvidenciaSolicitud.FOTO_RECOLECCION,
                    "archivo": self._archivo_png(),
                    "latitud": Decimal("14.072300"),
                    "longitud": Decimal("-87.192100"),
                    "capturada_en": timezone.now(),
                },
            )

    def test_recoleccion_exige_evidencia(self):
        self._transicion(EstadoSolicitud.HACIA_RECOLECCION)
        self._transicion(EstadoSolicitud.EN_RECOLECCION)

        with self.assertRaises(ValidationError):
            self._transicion(EstadoSolicitud.RECOLECTADA)

        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.EN_RECOLECCION)

    def test_endpoint_registra_y_descarga_archivo_autenticado(self):
        self.solicitud.estado = EstadoSolicitud.EN_RECOLECCION
        self.solicitud.save(update_fields=("estado", "actualizado_en"))
        cliente = APIClient()
        cliente.force_authenticate(user=self.usuario_repartidor)
        respuesta_registro = cliente.post(
            reverse(
                "solicitudes:evidencias:lista-registro",
                kwargs={"solicitud_id": self.solicitud.id},
            ),
            {
                "tipo": TipoEvidenciaSolicitud.FOTO_RECOLECCION,
                "archivo": self._archivo_png(),
                "latitud": "14.072300",
                "longitud": "-87.192100",
                "capturada_en": timezone.now().isoformat(),
            },
            format="multipart",
        )

        self.assertEqual(respuesta_registro.status_code, 201)
        evidencia_id = respuesta_registro.data["id"]
        respuesta_archivo = cliente.get(
            reverse(
                "solicitudes:evidencias:archivo",
                kwargs={
                    "solicitud_id": self.solicitud.id,
                    "evidencia_id": evidencia_id,
                },
            )
        )
        self.assertEqual(respuesta_archivo.status_code, 200)
        self.assertEqual(respuesta_archivo["Content-Type"], "image/png")
        self.assertEqual(respuesta_archivo["Cache-Control"], "private, no-store")
        respuesta_archivo.close()

    def test_entrega_exige_evidencia(self):
        self.solicitud.estado = EstadoSolicitud.EN_DESTINO
        self.solicitud.save(update_fields=("estado", "actualizado_en"))
        self.repartidor.estado_operativo = EstadoOperativoRepartidor.EN_RUTA
        self.repartidor.save(
            update_fields=("estado_operativo", "actualizado_en")
        )

        with self.assertRaises(ValidationError):
            self._transicion(EstadoSolicitud.ENTREGADA)

        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.EN_DESTINO)

    def test_flujo_completo_cierra_asignacion_y_libera_motorista(self):
        self._transicion(EstadoSolicitud.HACIA_RECOLECCION)
        self._transicion(EstadoSolicitud.EN_RECOLECCION)
        evidencia_recoleccion = self._registrar(
            TipoEvidenciaSolicitud.FOTO_RECOLECCION
        )
        self._transicion(EstadoSolicitud.RECOLECTADA)
        self._transicion(EstadoSolicitud.EN_TRANSITO)
        self._transicion(EstadoSolicitud.EN_DESTINO)
        evidencia_entrega = self._registrar(
            TipoEvidenciaSolicitud.FOTO_ENTREGA
        )
        self._transicion(EstadoSolicitud.ENTREGADA)

        self.solicitud.refresh_from_db()
        self.repartidor.refresh_from_db()
        asignacion = AsignacionSolicitud.objects.get(solicitud=self.solicitud)
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.ENTREGADA)
        self.assertIsNotNone(self.solicitud.recolectada_en)
        self.assertIsNotNone(self.solicitud.entregada_en)
        self.assertEqual(asignacion.estado, EstadoAsignacionSolicitud.FINALIZADA)
        self.assertIsNotNone(asignacion.finalizada_en)
        self.assertEqual(
            self.repartidor.estado_operativo,
            EstadoOperativoRepartidor.DISPONIBLE,
        )
        self.assertEqual(self.repartidor.capacidad, CapacidadRepartidor.VACIO)
        self.assertTrue(
            EventoSolicitud.objects.filter(
                solicitud=self.solicitud,
                tipo=TipoEventoSolicitud.ENTREGADA,
            ).exists()
        )
        self.assertTrue(
            archivo_existe_en_almacenamiento(
                evidencia_recoleccion.clave_almacenamiento
            )
        )
        self.assertTrue(
            archivo_existe_en_almacenamiento(
                evidencia_entrega.clave_almacenamiento
            )
        )


def archivo_existe_en_almacenamiento(clave):
    from django.core.files.storage import default_storage

    return default_storage.exists(clave)
