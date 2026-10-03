from decimal import Decimal
from datetime import timedelta
import uuid

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError

from apps.flota.models import Vehiculo
from apps.geografia.models import Pais
from apps.jornadas.models import JornadaRepartidor
from apps.organizaciones.models import Empresa, Sucursal
from apps.repartidores.models import Repartidor
from apps.repartidores.servicios import actualizar_operacion_repartidor
from apps.repartidores.selectores import listar_repartidores_disponibles
from apps.repartidores.opciones import EstadoOperativoRepartidor
from apps.notificaciones.models import NotificacionUsuario
from apps.notificaciones.opciones import TipoNotificacion
from apps.seguimiento.models import RegistroUbicacion
from apps.solicitudes.excepciones import LimiteSolicitudesRepartidor
from apps.solicitudes.models import (
    AsignacionSolicitud,
    EventoSolicitud,
    Solicitud,
    TipoServicio,
)
from apps.solicitudes.opciones import (
    EstadoAsignacionSolicitud,
    EstadoSolicitud,
    ModalidadSolicitud,
    PrioridadSolicitud,
    TipoAsignacionSolicitud,
    TipoEventoSolicitud,
)
from apps.solicitudes.selectores import listar_solicitudes_autorizadas
from apps.solicitudes.servicios import (
    asignar_solicitud_manualmente,
    cambiar_estado_solicitud,
    crear_solicitud,
    reintentar_solicitudes_pendientes,
)
from apps.ubicaciones.models import TipoUbicacion, Ubicacion, UbicacionEmpresa
from apps.ubicaciones.opciones import EstadoUbicacionEmpresa, OrigenUbicacion
from apps.usuarios.models import Rol, RolUsuario, Usuario
from apps.usuarios.opciones import TipoAlcanceRol


@override_settings(
    MODO_APLICACION="CORPORATIVO",
    PROVEEDOR_AUTENTICACION="LOCAL",
)
class PruebasAsignacionesSolicitud(TestCase):
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
            codigo="PRUEBA_ASIGNACION",
            nombre="Prueba de asignación",
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
            codigo="PRUEBA_ASIGNACION",
            nombre="Prueba de asignación",
        )
        cls.administrador = Usuario.objetos.create(
            correo="encargado.asignacion@analiza.test",
            nombres="Encargado",
            apellidos="Operativo",
            empresa=cls.empresa,
            es_superusuario=True,
        )
        cls.rol_repartidor = Rol.objetos.get(codigo="REPARTIDOR_CORPORATIVO")
        cls.repartidores = []
        for indice in (1, 2):
            usuario = Usuario.objetos.create(
                correo=f"motorista{indice}@analiza.test",
                nombres=f"Motorista {indice}",
                apellidos="Prueba",
                empresa=cls.empresa,
            )
            RolUsuario.objetos.create(
                usuario=usuario,
                rol=cls.rol_repartidor,
                tipo_alcance=TipoAlcanceRol.EMPRESA,
                empresa=cls.empresa,
                asignado_por=cls.administrador,
            )
            vehiculo = Vehiculo.objects.create(
                empresa=cls.empresa,
                placa=f"PRU-{indice}",
                tipo="MOTOCICLETA",
            )
            cls.repartidores.append(
                Repartidor.objects.create(
                    usuario=usuario,
                    empresa=cls.empresa,
                    vehiculo=vehiculo,
                    estado_operativo=EstadoOperativoRepartidor.DISPONIBLE,
                )
            )

    def setUp(self):
        self.solicitud = Solicitud.objects.create(
            numero=f"SOL-PRUEBA-{Solicitud.objects.count() + 1}",
            empresa=self.empresa,
            solicitada_por=self.administrador,
            prioridad="NORMAL",
            tipo_servicio=self.tipo_servicio,
            origen=self.origen,
            destino=self.destino,
        )

    def _datos_creacion_automatica(self):
        for ubicacion in (self.origen, self.destino):
            ubicacion.localidad = "Tegucigalpa"
            ubicacion.save(update_fields=("localidad", "actualizado_en"))
            UbicacionEmpresa.objects.create(
                empresa=self.empresa,
                ubicacion=ubicacion,
                estado=EstadoUbicacionEmpresa.APROBADO,
                permite_origen=True,
                permite_destino=True,
            )
        sucursal = Sucursal.objects.create(
            empresa=self.empresa,
            nombre="Sucursal de origen",
            ubicacion=self.origen,
        )
        Sucursal.objects.create(
            empresa=self.empresa,
            nombre="Sucursal de destino",
            ubicacion=self.destino,
        )
        return {
            "empresa_id": self.empresa.id,
            "sucursal_id": sucursal.id,
            "prioridad": PrioridadSolicitud.NORMAL,
            "modalidad": ModalidadSolicitud.ENTRE_SUCURSALES,
            "tipo_servicio_id": self.tipo_servicio.id,
            "origen_id": self.origen.id,
            "destino_id": self.destino.id,
            "articulos": [{"tipo_articulo": "Documentos", "cantidad": 1}],
        }

    def _registrar_gps(self, repartidor, latitud, longitud):
        jornada = JornadaRepartidor.objects.create(repartidor=repartidor)
        RegistroUbicacion.objects.create(
            id_cliente=uuid.uuid4(),
            repartidor=repartidor,
            jornada=jornada,
            latitud=Decimal(latitud),
            longitud=Decimal(longitud),
            registrada_en=timezone.now(),
        )

    def test_asignacion_inicial_conserva_historial_y_evento(self):
        asignar_solicitud_manualmente(
            self.administrador,
            self.solicitud.id,
            {"repartidor_id": self.repartidores[0].id},
        )

        self.solicitud.refresh_from_db()
        asignacion = AsignacionSolicitud.objects.get(solicitud=self.solicitud)
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.ASIGNADA)
        self.assertEqual(
            self.solicitud.repartidor_asignado_id,
            self.repartidores[0].id,
        )
        self.assertEqual(asignacion.estado, EstadoAsignacionSolicitud.ACTIVA)
        self.assertTrue(
            EventoSolicitud.objects.filter(
                solicitud=self.solicitud,
                tipo=TipoEventoSolicitud.ASIGNADA,
            ).exists()
        )

    def test_reasignacion_cierra_anterior_y_crea_otra(self):
        asignar_solicitud_manualmente(
            self.administrador,
            self.solicitud.id,
            {"repartidor_id": self.repartidores[0].id},
        )
        asignar_solicitud_manualmente(
            self.administrador,
            self.solicitud.id,
            {
                "repartidor_id": self.repartidores[1].id,
                "motivo": "Cambio operativo",
            },
        )

        self.solicitud.refresh_from_db()
        estados = list(
            AsignacionSolicitud.objects.filter(solicitud=self.solicitud)
            .values_list("estado", flat=True)
        )
        self.assertCountEqual(
            estados,
            [EstadoAsignacionSolicitud.REASIGNADA, EstadoAsignacionSolicitud.ACTIVA],
        )
        self.assertEqual(
            self.solicitud.repartidor_asignado_id,
            self.repartidores[1].id,
        )
        self.assertTrue(
            EventoSolicitud.objects.filter(
                solicitud=self.solicitud,
                tipo=TipoEventoSolicitud.REASIGNADA,
            ).exists()
        )

    def test_rechaza_motorista_no_disponible(self):
        repartidor = self.repartidores[0]
        repartidor.estado_operativo = EstadoOperativoRepartidor.PAUSADO
        repartidor.save(update_fields=("estado_operativo", "actualizado_en"))

        with self.assertRaises(ValidationError):
            asignar_solicitud_manualmente(
                self.administrador,
                self.solicitud.id,
                {"repartidor_id": repartidor.id},
            )

        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.PENDIENTE)
        self.assertFalse(
            AsignacionSolicitud.objects.filter(solicitud=self.solicitud).exists()
        )

    def test_motorista_solo_ve_solicitudes_asignadas(self):
        asignar_solicitud_manualmente(
            self.administrador,
            self.solicitud.id,
            {"repartidor_id": self.repartidores[0].id},
        )

        visibles = listar_solicitudes_autorizadas(
            self.repartidores[0].usuario
        )
        no_visibles = listar_solicitudes_autorizadas(
            self.repartidores[1].usuario
        )

        self.assertTrue(visibles.filter(pk=self.solicitud.pk).exists())
        self.assertFalse(no_visibles.filter(pk=self.solicitud.pk).exists())

    def test_limite_cinco_y_disponibilidad_calculada(self):
        repartidor = self.repartidores[0]
        solicitudes = [self.solicitud]
        for indice in range(2, 7):
            solicitudes.append(
                Solicitud.objects.create(
                    numero=f"SOL-LIMITE-{indice}",
                    empresa=self.empresa,
                    solicitada_por=self.administrador,
                    prioridad="NORMAL",
                    tipo_servicio=self.tipo_servicio,
                    origen=self.origen,
                    destino=self.destino,
                )
            )
        for solicitud in solicitudes[:5]:
            asignar_solicitud_manualmente(
                self.administrador,
                solicitud.id,
                {"repartidor_id": repartidor.id},
            )
        repartidor.refresh_from_db()
        self.assertEqual(repartidor.capacidad, "FULL")
        self.assertFalse(
            listar_repartidores_disponibles(self.administrador).filter(
                id=repartidor.id
            ).exists()
        )
        with self.assertRaises(LimiteSolicitudesRepartidor) as captura:
            asignar_solicitud_manualmente(
                self.administrador,
                solicitudes[5].id,
                {"repartidor_id": repartidor.id},
            )
        self.assertEqual(captura.exception.status_code, 409)
        self.assertIn("repartidor_id", captura.exception.detail)
        cliente = APIClient()
        cliente.force_authenticate(user=self.administrador)
        respuesta = cliente.post(
            f"/api/v1/solicitudes/{solicitudes[5].id}/asignaciones/",
            {"repartidor_id": str(repartidor.id)},
            format="json",
        )
        self.assertEqual(respuesta.status_code, 409)
        self.assertIn("repartidor_id", respuesta.data)
        solicitudes[5].refresh_from_db()
        self.assertEqual(solicitudes[5].estado, EstadoSolicitud.PENDIENTE)

    def test_reasignacion_recalcula_y_notifica_a_ambos(self):
        primero, segundo = self.repartidores
        asignar_solicitud_manualmente(
            self.administrador,
            self.solicitud.id,
            {"repartidor_id": primero.id},
        )
        primero.refresh_from_db()
        self.assertEqual(primero.capacidad, "AVAILABLE_SPACE")
        asignar_solicitud_manualmente(
            self.administrador,
            self.solicitud.id,
            {"repartidor_id": segundo.id},
        )
        primero.refresh_from_db()
        segundo.refresh_from_db()
        self.assertEqual(primero.capacidad, "EMPTY")
        self.assertEqual(segundo.capacidad, "AVAILABLE_SPACE")
        self.assertEqual(
            list(
                NotificacionUsuario.objects.filter(usuario=primero.usuario)
                .order_by("creado_en")
                .values_list("tipo", flat=True)
            ),
            [
                TipoNotificacion.SOLICITUD_ASIGNADA,
                TipoNotificacion.SOLICITUD_RETIRADA,
            ],
        )
        self.assertTrue(
            NotificacionUsuario.objects.filter(
                usuario=segundo.usuario,
                tipo=TipoNotificacion.SOLICITUD_REASIGNADA,
            ).exists()
        )

    def test_prioritaria_crea_una_notificacion_especial(self):
        self.solicitud.prioridad = "PRIORITY"
        self.solicitud.save(update_fields=("prioridad", "actualizado_en"))
        asignar_solicitud_manualmente(
            self.administrador,
            self.solicitud.id,
            {"repartidor_id": self.repartidores[0].id},
        )
        self.assertEqual(
            list(
                NotificacionUsuario.objects.filter(
                    usuario=self.repartidores[0].usuario
                ).values_list("tipo", flat=True)
            ),
            [TipoNotificacion.SOLICITUD_PRIORITARIA],
        )

    def test_cancelar_libera_capacidad_automaticamente(self):
        repartidor = self.repartidores[0]
        asignar_solicitud_manualmente(
            self.administrador,
            self.solicitud.id,
            {"repartidor_id": repartidor.id},
        )
        cambiar_estado_solicitud(
            self.administrador,
            self.solicitud.id,
            {"estado_destino": EstadoSolicitud.CANCELADA, "motivo": "Prueba"},
        )
        repartidor.refresh_from_db()
        self.assertEqual(repartidor.capacidad, "EMPTY")
        self.assertTrue(
            listar_repartidores_disponibles(self.administrador).filter(
                id=repartidor.id
            ).exists()
        )

    def test_notificaciones_http_propiedad_conteo_y_enlace(self):
        primero, segundo = self.repartidores
        asignar_solicitud_manualmente(
            self.administrador,
            self.solicitud.id,
            {"repartidor_id": primero.id},
        )
        notificacion = NotificacionUsuario.objects.get(usuario=primero.usuario)
        cliente = APIClient()
        cliente.force_authenticate(user=primero.usuario)
        respuesta = cliente.get("/api/v1/notificaciones/")
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data["conteo"], 1)
        self.assertEqual(
            respuesta.data["resultados"][0]["ruta"],
            f"/solicitudes/{self.solicitud.id}",
        )
        self.assertEqual(
            respuesta.data["resultados"][0]["enlace_profundo"],
            f"vitago-corporate:///solicitudes/{self.solicitud.id}",
        )
        self.assertEqual(
            cliente.get("/api/v1/notificaciones/conteo-no-leidas/").data,
            {"conteo_no_leidas": 1},
        )
        cliente.force_authenticate(user=segundo.usuario)
        self.assertEqual(
            cliente.post(
                f"/api/v1/notificaciones/{notificacion.id}/marcar-leida/"
            ).status_code,
            404,
        )
        cliente.force_authenticate(user=primero.usuario)
        self.assertEqual(
            cliente.post(
                f"/api/v1/notificaciones/{notificacion.id}/marcar-leida/"
            ).status_code,
            200,
        )
        self.assertEqual(
            cliente.get("/api/v1/notificaciones/conteo-no-leidas/").data,
            {"conteo_no_leidas": 0},
        )

    def test_listado_http_disponibles_no_filtra_activo_omitido(self):
        cliente = APIClient()
        cliente.force_authenticate(user=self.administrador)
        respuesta = cliente.get(
            "/api/v1/repartidores/disponibles/",
            {"empresa_id": str(self.empresa.id)},
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data["conteo"], 2)

    def test_creacion_asigna_al_gps_mas_cercano_y_notifica_solo_a_el(self):
        datos = self._datos_creacion_automatica()
        lejos, cerca = self.repartidores
        self._registrar_gps(lejos, "14.200000", "-87.300000")
        self._registrar_gps(cerca, "14.073000", "-87.192000")

        solicitud = crear_solicitud(self.administrador, datos)

        self.assertEqual(solicitud.estado, EstadoSolicitud.ASIGNADA)
        self.assertEqual(solicitud.repartidor_asignado_id, cerca.id)
        asignacion = AsignacionSolicitud.objects.get(solicitud=solicitud)
        self.assertEqual(asignacion.tipo, TipoAsignacionSolicitud.AUTOMATICA)
        self.assertEqual(asignacion.asignada_por_id, self.administrador.id)
        evento = EventoSolicitud.objects.get(
            solicitud=solicitud, tipo=TipoEventoSolicitud.ASIGNADA
        )
        self.assertIsNotNone(evento.metadatos["distancia_gps_linea_recta_km"])
        self.assertEqual(
            NotificacionUsuario.objects.filter(usuario=cerca.usuario).count(), 1
        )
        self.assertFalse(
            NotificacionUsuario.objects.filter(usuario=lejos.usuario).exists()
        )

    def test_post_creacion_responde_ya_asignada(self):
        datos = self._datos_creacion_automatica()
        cliente = APIClient()
        cliente.force_authenticate(user=self.administrador)
        respuesta = cliente.post(
            "/api/v1/solicitudes/",
            {
                **datos,
                "empresa_id": str(datos["empresa_id"]),
                "sucursal_id": str(datos["sucursal_id"]),
                "tipo_servicio_id": str(datos["tipo_servicio_id"]),
                "origen_id": str(datos["origen_id"]),
                "destino_id": str(datos["destino_id"]),
            },
            format="json",
        )
        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual(respuesta.data["estado"], EstadoSolicitud.ASIGNADA)
        self.assertIsNotNone(respuesta.data["repartidor_asignado_id"])

    def test_creacion_omite_mas_cercano_lleno_o_con_prioritario(self):
        datos = self._datos_creacion_automatica()
        cerca, lejos = self.repartidores
        self._registrar_gps(cerca, "14.073000", "-87.192000")
        self._registrar_gps(lejos, "14.200000", "-87.300000")
        self.solicitud.repartidor_asignado = cerca
        self.solicitud.prioridad = PrioridadSolicitud.PRIORITARIA
        self.solicitud.estado = EstadoSolicitud.ASIGNADA
        self.solicitud.save(
            update_fields=(
                "repartidor_asignado", "prioridad", "estado", "actualizado_en"
            )
        )
        solicitud = crear_solicitud(self.administrador, datos)
        self.assertEqual(solicitud.repartidor_asignado_id, lejos.id)

    def test_creacion_omite_motorista_lleno(self):
        datos = self._datos_creacion_automatica()
        cerca, lejos = self.repartidores
        self._registrar_gps(cerca, "14.073000", "-87.192000")
        self._registrar_gps(lejos, "14.200000", "-87.300000")
        for indice in range(5):
            Solicitud.objects.create(
                numero=f"SOL-AUTO-LLENO-{indice}",
                empresa=self.empresa,
                solicitada_por=self.administrador,
                prioridad=PrioridadSolicitud.NORMAL,
                tipo_servicio=self.tipo_servicio,
                origen=self.origen,
                destino=self.destino,
                estado=EstadoSolicitud.ASIGNADA,
                repartidor_asignado=cerca,
            )
        solicitud = crear_solicitud(self.administrador, datos)
        self.assertEqual(solicitud.repartidor_asignado_id, lejos.id)

    def test_motorista_sin_gps_queda_despues_de_uno_con_gps(self):
        datos = self._datos_creacion_automatica()
        sin_gps, con_gps = self.repartidores
        self._registrar_gps(con_gps, "14.200000", "-87.300000")
        solicitud = crear_solicitud(self.administrador, datos)
        self.assertEqual(solicitud.repartidor_asignado_id, con_gps.id)
        self.assertFalse(
            NotificacionUsuario.objects.filter(usuario=sin_gps.usuario).exists()
        )

    def test_sin_gps_se_asigna_un_motorista_disponible(self):
        datos = self._datos_creacion_automatica()
        solicitud = crear_solicitud(self.administrador, datos)
        self.assertEqual(solicitud.estado, EstadoSolicitud.ASIGNADA)
        self.assertIn(
            solicitud.repartidor_asignado_id,
            [repartidor.id for repartidor in self.repartidores],
        )
        asignacion = AsignacionSolicitud.objects.get(solicitud=solicitud)
        self.assertIn("sin GPS", asignacion.motivo)

    def test_sin_motoristas_elegibles_permanece_pendiente(self):
        datos = self._datos_creacion_automatica()
        Repartidor.objects.filter(id__in=[r.id for r in self.repartidores]).update(
            estado_operativo=EstadoOperativoRepartidor.PAUSADO
        )
        solicitud = crear_solicitud(self.administrador, datos)
        self.assertEqual(solicitud.estado, EstadoSolicitud.PENDIENTE)
        self.assertIsNone(solicitud.repartidor_asignado_id)
        self.assertFalse(NotificacionUsuario.objects.filter(solicitud=solicitud).exists())

    def test_al_volver_disponible_reintenta_pendiente_y_notifica(self):
        Repartidor.objects.filter(
            id__in=[repartidor.id for repartidor in self.repartidores]
        ).update(estado_operativo=EstadoOperativoRepartidor.PAUSADO)
        elegido = self.repartidores[0]

        with self.captureOnCommitCallbacks(execute=True):
            actualizar_operacion_repartidor(
                self.administrador,
                elegido.id,
                {"estado_operativo": EstadoOperativoRepartidor.DISPONIBLE},
            )

        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, EstadoSolicitud.ASIGNADA)
        self.assertEqual(self.solicitud.repartidor_asignado_id, elegido.id)
        self.assertEqual(
            AsignacionSolicitud.objects.filter(solicitud=self.solicitud).count(), 1
        )
        self.assertEqual(
            NotificacionUsuario.objects.filter(
                solicitud=self.solicitud, usuario=elegido.usuario
            ).count(),
            1,
        )
        self.assertEqual(reintentar_solicitudes_pendientes(self.empresa.id), 0)

    def test_pendiente_se_revisa_tras_commit_si_motorista_se_habilito(self):
        Repartidor.objects.filter(
            id__in=[repartidor.id for repartidor in self.repartidores]
        ).update(estado_operativo=EstadoOperativoRepartidor.PAUSADO)
        datos = self._datos_creacion_automatica()

        with self.captureOnCommitCallbacks(execute=True):
            solicitud = crear_solicitud(self.administrador, datos)
            self.assertEqual(solicitud.estado, EstadoSolicitud.PENDIENTE)
            Repartidor.objects.filter(id=self.repartidores[0].id).update(
                estado_operativo=EstadoOperativoRepartidor.DISPONIBLE
            )

        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, EstadoSolicitud.ASIGNADA)
        self.assertEqual(solicitud.repartidor_asignado_id, self.repartidores[0].id)
        self.assertEqual(
            AsignacionSolicitud.objects.filter(solicitud=solicitud).count(), 1
        )

    def test_reintento_respeta_cupo_y_antiguedad(self):
        Solicitud.objects.filter(id=self.solicitud.id).update(
            creado_en=timezone.now() - timedelta(days=1)
        )
        Repartidor.objects.filter(
            id__in=[repartidor.id for repartidor in self.repartidores]
        ).update(estado_operativo=EstadoOperativoRepartidor.PAUSADO)
        pendientes = [self.solicitud]
        for indice in range(6):
            pendientes.append(
                Solicitud.objects.create(
                    numero=f"SOL-REINTENTO-{indice}",
                    empresa=self.empresa,
                    solicitada_por=self.administrador,
                    prioridad=PrioridadSolicitud.NORMAL,
                    tipo_servicio=self.tipo_servicio,
                    origen=self.origen,
                    destino=self.destino,
                )
            )

        with self.captureOnCommitCallbacks(execute=True):
            actualizar_operacion_repartidor(
                self.administrador,
                self.repartidores[0].id,
                {"estado_operativo": EstadoOperativoRepartidor.DISPONIBLE},
            )

        self.assertEqual(
            Solicitud.objects.filter(
                id__in=[solicitud.id for solicitud in pendientes],
                estado=EstadoSolicitud.ASIGNADA,
            ).count(),
            5,
        )
        self.assertEqual(
            Solicitud.objects.filter(
                id__in=[solicitud.id for solicitud in pendientes],
                estado=EstadoSolicitud.PENDIENTE,
            ).count(),
            2,
        )
        self.assertEqual(
            Solicitud.objects.get(id=pendientes[0].id).estado,
            EstadoSolicitud.ASIGNADA,
            list(
                Solicitud.objects.filter(
                    id__in=[solicitud.id for solicitud in pendientes]
                ).order_by("creado_en", "id").values_list("numero", "estado")
            ),
        )

    def test_cierre_de_solicitud_libera_cupo_y_reintenta(self):
        Repartidor.objects.filter(id=self.repartidores[1].id).update(
            estado_operativo=EstadoOperativoRepartidor.PAUSADO
        )
        asignar_solicitud_manualmente(
            self.administrador,
            self.solicitud.id,
            {"repartidor_id": self.repartidores[0].id},
        )
        pendiente = Solicitud.objects.create(
            numero="SOL-REINTENTO-AL-CERRAR",
            empresa=self.empresa,
            solicitada_por=self.administrador,
            prioridad=PrioridadSolicitud.NORMAL,
            tipo_servicio=self.tipo_servicio,
            origen=self.origen,
            destino=self.destino,
        )

        with self.captureOnCommitCallbacks(execute=True):
            cambiar_estado_solicitud(
                self.administrador,
                self.solicitud.id,
                {
                    "estado_destino": EstadoSolicitud.CANCELADA,
                    "motivo": "Prueba de liberación de cupo",
                },
            )

        pendiente.refresh_from_db()
        self.assertEqual(pendiente.estado, EstadoSolicitud.ASIGNADA)
        self.assertEqual(
            pendiente.repartidor_asignado_id, self.repartidores[0].id
        )

    def test_reasignacion_reintenta_pendiente_con_motorista_liberado(self):
        anterior, nuevo = self.repartidores
        asignar_solicitud_manualmente(
            self.administrador,
            self.solicitud.id,
            {"repartidor_id": anterior.id},
        )
        pendiente = Solicitud.objects.create(
            numero="SOL-REINTENTO-REASIGNACION",
            empresa=self.empresa,
            solicitada_por=self.administrador,
            prioridad=PrioridadSolicitud.NORMAL,
            tipo_servicio=self.tipo_servicio,
            origen=self.origen,
            destino=self.destino,
        )

        with self.captureOnCommitCallbacks(execute=True):
            asignar_solicitud_manualmente(
                self.administrador,
                self.solicitud.id,
                {"repartidor_id": nuevo.id},
            )
            Repartidor.objects.filter(id=nuevo.id).update(
                estado_operativo=EstadoOperativoRepartidor.PAUSADO
            )

        pendiente.refresh_from_db()
        self.assertEqual(pendiente.estado, EstadoSolicitud.ASIGNADA)
        self.assertEqual(pendiente.repartidor_asignado_id, anterior.id)
