import tempfile
from contextlib import nullcontext
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

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
from apps.jornadas.models import JornadaRepartidor
from apps.jornadas.servicios import finalizar_jornada
from apps.nucleo.tests.imagenes import crear_imagen_prueba
from apps.organizaciones.models import Empresa
from apps.repartidores.models import Repartidor
from apps.repartidores.opciones import (
    CapacidadRepartidor,
    EstadoOperativoRepartidor,
)
from apps.seguimiento.models import RegistroUbicacion
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
        self.jornada = JornadaRepartidor.objects.create(repartidor=self.repartidor)
        self.solicitud = Solicitud.objects.create(
            cantidad_tubos=1,
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
        return crear_imagen_prueba(nombre=nombre)

    def _registrar(self, tipo):
        return registrar_evidencia(
            self.usuario_repartidor,
            self.solicitud.id,
            {
                "tipo": tipo,
                **({"temperatura_contenedor_c": "4.50"} if tipo == "FOTO_RECOLECCION" else {}),
                "archivo": self._archivo_png(),
                "latitud": Decimal("14.072300"),
                "longitud": Decimal("-87.192100"),
                "capturada_en": timezone.now(),
                "notas": "Evidencia de prueba",
            },
        )

    def _transicion(self, estado_destino):
        if estado_destino in (
            EstadoSolicitud.EN_RECOLECCION,
            EstadoSolicitud.EN_DESTINO,
        ):
            from apps.seguimiento.llegadas import detectar_llegada

            ahora = timezone.now()
            inicio_desplazamiento = ahora - timedelta(seconds=40)
            # Este helper comprime el viaje de la prueba; las capturas deben
            # suceder después del inicio real de la etapa y de su asignación.
            JornadaRepartidor.objects.filter(pk=self.jornada.pk).update(
                iniciada_en=inicio_desplazamiento - timedelta(seconds=1)
            )
            AsignacionSolicitud.objects.filter(
                solicitud=self.solicitud,
                repartidor=self.repartidor,
                estado=EstadoAsignacionSolicitud.ACTIVA,
            ).update(
                asignada_en=inicio_desplazamiento,
                aceptada_en=inicio_desplazamiento,
            )
            Solicitud.objects.filter(pk=self.solicitud.pk).update(
                asignada_en=inicio_desplazamiento
            )
            tipo_inicio = (
                TipoEventoSolicitud.HACIA_RECOLECCION
                if estado_destino == EstadoSolicitud.EN_RECOLECCION
                else TipoEventoSolicitud.EN_TRANSITO
            )
            EventoSolicitud.objects.filter(
                solicitud=self.solicitud,
                repartidor=self.repartidor,
                tipo=tipo_inicio,
            ).update(creado_en=inicio_desplazamiento)
            # La primera parada ya atendida no debe mezclarse con las tres
            # capturas consecutivas de la siguiente etapa de esta misma prueba.
            RegistroUbicacion.objects.filter(jornada=self.jornada).update(
                registrada_en=inicio_desplazamiento,
                creado_en=inicio_desplazamiento,
            )
            ubicacion = (
                self.origen
                if estado_destino == EstadoSolicitud.EN_RECOLECCION
                else self.destino
            )
            sesion_gps = uuid4()
            for secuencia, retraso in enumerate((20, 10, 0), start=1):
                capturada_en = ahora - timedelta(seconds=retraso)
                registro = RegistroUbicacion.objects.create(
                    id_cliente=uuid4(),
                    sesion_gps=sesion_gps,
                    secuencia=secuencia,
                    repartidor=self.repartidor,
                    jornada=self.jornada,
                    latitud=ubicacion.latitud,
                    longitud=ubicacion.longitud,
                    precision_metros=Decimal("5"),
                    velocidad_metros_segundo=Decimal("0"),
                    registrada_en=capturada_en,
                    es_operativo=True,
                )
                RegistroUbicacion.objects.filter(pk=registro.pk).update(
                    creado_en=capturada_en
                )
            llegada = detectar_llegada(
                self.usuario_repartidor, self.repartidor.pk, self.jornada.pk
            )
            self.assertIsNotNone(llegada)
            self.solicitud.refresh_from_db()
            self.assertEqual(self.solicitud.estado, estado_destino)
            return self.solicitud

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

    def test_api_fecha_oficial_ignora_reloj_del_telefono_y_admite_omitir_fecha(self):
        self.solicitud.estado = EstadoSolicitud.EN_RECOLECCION
        self.solicitud.save()
        ahora = timezone.now()
        cliente = APIClient()
        cliente.force_authenticate(self.usuario_repartidor)
        for fecha in (None, "fecha-manipulada", (ahora - timedelta(days=3650)).isoformat(),
                      (ahora + timedelta(days=3650)).isoformat()):
            # Cada caso simula una etapa aún pendiente de su foto.
            Solicitud.objects.filter(pk=self.solicitud.pk).update(estado=EstadoSolicitud.EN_RECOLECCION)
            datos = {"temperatura_contenedor_c": "4.50", "tipo": "FOTO_RECOLECCION", "archivo": self._archivo_png(),
                     "latitud": "14.072300", "longitud": "-87.192100"}
            if fecha is not None:
                datos["capturada_en"] = fecha
            with self.subTest(fecha=fecha), patch("apps.evidencias.servicios.timezone.now", return_value=ahora):
                respuesta = cliente.post(
                    reverse("solicitudes:evidencias:lista-registro", args=[self.solicitud.pk]),
                    datos, format="multipart",
                )
                self.assertEqual(respuesta.status_code, 201, respuesta.data)
                evidencia = EvidenciaSolicitud.objects.get(pk=respuesta.data["id"])
                self.assertEqual(evidencia.capturada_en, ahora)
                evento = EventoSolicitud.objects.get(metadatos__evidencia_id=str(evidencia.pk))
                self.assertEqual(evento.metadatos["capturada_en"], ahora.isoformat())

    def test_servicio_tampoco_confia_en_fecha_recibida_sin_serializador(self):
        self.solicitud.estado = EstadoSolicitud.EN_RECOLECCION
        self.solicitud.save()
        ahora = timezone.now()
        with patch("apps.evidencias.servicios.timezone.now", return_value=ahora):
            evidencia = registrar_evidencia(self.usuario_repartidor, self.solicitud.pk, {
                "temperatura_contenedor_c": "4.50", "tipo": "FOTO_RECOLECCION", "archivo": self._archivo_png(),
                "latitud": self.origen.latitud, "longitud": self.origen.longitud,
                "capturada_en": ahora + timedelta(days=3650),
            })
        self.assertEqual(evidencia.capturada_en, ahora)

    def test_compensacion_preserva_error_original_y_revierte_filas(self):
        self.solicitud.estado = EstadoSolicitud.EN_RECOLECCION
        self.solicitud.save()
        for fallo_limpieza in (None, OSError("Almacenamiento no disponible")):
            original = RuntimeError("Fallo de auditoría")
            with self.subTest(limpieza_falla=bool(fallo_limpieza)), \
                 patch("apps.evidencias.servicios.default_storage.save", return_value="evidencias/nueva.png"), \
                 patch("apps.evidencias.servicios.default_storage.delete", side_effect=fallo_limpieza) as eliminar, \
                 patch("apps.evidencias.servicios.EventoSolicitud.objects.create", side_effect=original), \
                 (self.assertLogs("vitago.api", level="ERROR") if fallo_limpieza else nullcontext()):
                with self.assertRaises(RuntimeError) as error:
                    self._registrar(TipoEvidenciaSolicitud.FOTO_RECOLECCION)
                self.assertIs(error.exception, original)
                eliminar.assert_called_once_with("evidencias/nueva.png")
            self.assertFalse(EvidenciaSolicitud.objects.exists())
            self.assertFalse(EventoSolicitud.objects.exists())

        self.assertFalse(EvidenciaSolicitud.objects.exists())

    def test_solo_motorista_asignado_puede_registrar_evidencia(self):
        self.solicitud.estado = EstadoSolicitud.EN_RECOLECCION
        self.solicitud.save(update_fields=("estado", "actualizado_en"))

        with self.assertRaises(PermissionDenied):
            registrar_evidencia(
                self.administrador,
                self.solicitud.id,
                {
                    "temperatura_contenedor_c": "4.50", "tipo": TipoEvidenciaSolicitud.FOTO_RECOLECCION,
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

    def test_api_foto_corrupta_no_crea_evidencia_ni_permite_recoleccion(self):
        self._transicion(EstadoSolicitud.HACIA_RECOLECCION)
        self._transicion(EstadoSolicitud.EN_RECOLECCION)
        cliente = APIClient()
        cliente.force_authenticate(self.usuario_repartidor)
        respuesta = cliente.post(
            reverse("solicitudes:evidencias:lista-registro", kwargs={"solicitud_id": self.solicitud.id}),
            {"temperatura_contenedor_c": "4.50", "tipo": TipoEvidenciaSolicitud.FOTO_RECOLECCION,
             "archivo": SimpleUploadedFile("corrupta.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 32, content_type="image/png"),
             "latitud": "14.072300", "longitud": "-87.192100", "capturada_en": timezone.now().isoformat()},
            format="multipart",
        )
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("archivo", respuesta.data)
        self.assertFalse(EvidenciaSolicitud.objects.exists())
        with self.assertRaises(ValidationError):
            self._transicion(EstadoSolicitud.RECOLECTADA)

    def test_todas_las_transiciones_operativas_exigen_jornada(self):
        self.jornada.delete()  # Solo datos temporales de esta prueba.
        cliente = APIClient()
        cliente.force_authenticate(self.usuario_repartidor)
        for origen, destino in (
            (EstadoSolicitud.ASIGNADA, EstadoSolicitud.HACIA_RECOLECCION),
            (EstadoSolicitud.HACIA_RECOLECCION, EstadoSolicitud.EN_RECOLECCION),
            (EstadoSolicitud.EN_RECOLECCION, EstadoSolicitud.RECOLECTADA),
            (EstadoSolicitud.RECOLECTADA, EstadoSolicitud.EN_TRANSITO),
            (EstadoSolicitud.EN_TRANSITO, EstadoSolicitud.EN_DESTINO),
            (EstadoSolicitud.EN_DESTINO, EstadoSolicitud.ENTREGADA),
            (EstadoSolicitud.EN_RECOLECCION, EstadoSolicitud.RECOLECCION_FALLIDA),
            (EstadoSolicitud.EN_TRANSITO, EstadoSolicitud.ENTREGA_FALLIDA),
        ):
            with self.subTest(destino=destino):
                Solicitud.objects.filter(pk=self.solicitud.pk).update(estado=origen)
                respuesta = cliente.post(
                    reverse("solicitudes:transicion", args=[self.solicitud.id]),
                    {"estado_destino": destino, "motivo": "Prueba sin jornada"}, format="json",
                )
                self.assertEqual(respuesta.status_code, 400)
                self.assertIn("jornada", respuesta.data)
                self.solicitud.refresh_from_db()
                self.assertEqual(self.solicitud.estado, origen)
        self.assertFalse(EventoSolicitud.objects.exists())
        self.assertEqual(AsignacionSolicitud.objects.get(solicitud=self.solicitud).estado, EstadoAsignacionSolicitud.ACTIVA)

    def test_jornada_finalizada_no_habilita_operacion(self):
        self.jornada.estado = "FINALIZADA"
        self.jornada.finalizada_en = timezone.now()
        self.jornada.save(update_fields=("estado", "finalizada_en", "actualizado_en"))
        with self.assertRaises(ValidationError) as error:
            self._transicion(EstadoSolicitud.HACIA_RECOLECCION)
        self.assertIn("jornada", error.exception.detail)

    def test_cancelacion_administrativa_no_exige_jornada(self):
        self.jornada.delete()
        solicitud = cambiar_estado_solicitud(self.administrador, self.solicitud.id, {
            "estado_destino": EstadoSolicitud.CANCELADA, "motivo": "Cancelación administrativa de prueba",
        })
        self.assertEqual(solicitud.estado, EstadoSolicitud.CANCELADA)

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
                "temperatura_contenedor_c": "4.50", "tipo": TipoEvidenciaSolicitud.FOTO_RECOLECCION,
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
        # Consumir el stream usa el cierre protegido del cliente de Django;
        # close() directo cierra la conexión PostgreSQL del TestCase.
        contenido = b"".join(respuesta_archivo.streaming_content)
        self.assertTrue(contenido.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertTrue(respuesta_archivo.closed)

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
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.EN_TRANSITO)
        self._transicion(EstadoSolicitud.EN_DESTINO)
        evidencia_entrega = self._registrar(
            TipoEvidenciaSolicitud.FOTO_ENTREGA
        )

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
        self.assertEqual(asignacion.finalizada_en, self.solicitud.entregada_en)
        jornada = finalizar_jornada(self.usuario_repartidor, self.jornada.pk, {})
        self.assertEqual(
            (jornada.servicios_completados, jornada.entregas_completadas,
             jornada.recolecciones_completadas, jornada.servicios_normales),
            (1, 1, 1, 1),
        )


def archivo_existe_en_almacenamiento(clave):
    from django.core.files.storage import default_storage

    return default_storage.exists(clave)
