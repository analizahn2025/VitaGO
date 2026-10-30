"""Carreras operativas reales, exclusivamente en PostgreSQL de pruebas."""

import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier, Event

from django.db import connection, connections, transaction
from django.test import TransactionTestCase, override_settings, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.test import APIClient

from apps.evidencias.models import EvidenciaSolicitud
from apps.evidencias.opciones import TipoEvidenciaSolicitud
from apps.flota.models import Vehiculo
from apps.geografia.models import Pais
from apps.jornadas.models import JornadaRepartidor
from apps.notificaciones.models import NotificacionUsuario
from apps.notificaciones.opciones import TipoNotificacion
from apps.organizaciones.models import Empresa, Sucursal
from apps.repartidores.capacidad import calcular_capacidad, contar_solicitudes_activas, obtener_carga_recipientes
from apps.repartidores.models import Repartidor
from apps.repartidores.selectores import listar_repartidores_disponibles
from apps.rutas.models import RutaRepartidor
from apps.rutas.selectores import obtener_paradas_operativas
from apps.seguimiento.models import RegistroUbicacion
from apps.solicitudes.contingencias import cerrar_solicitud_vencida, retirar_servicio_por_suspension
from apps.solicitudes.models import AsignacionSolicitud, EventoSolicitud, Solicitud, TipoServicio
from apps.solicitudes.opciones import ESTADOS_SOLICITUD_ACTIVOS
from apps.solicitudes.servicios import asignar_solicitud_manualmente, reintentar_solicitudes_pendientes
from apps.ubicaciones.models import TipoUbicacion, Ubicacion, UbicacionEmpresa
from apps.usuarios.models import Permiso, PermisoRol, Rol, RolUsuario, Usuario


@skipUnlessDBFeature("has_select_for_update")
@override_settings(
    MODO_APLICACION="CORPORATIVO", PROVEEDOR_AUTENTICACION="LOCAL",
    ASIGNACION_REQUIERE_GPS_VIGENTE=True,
)
class PruebasConcurrenciaAsignaciones(TransactionTestCase):
    @classmethod
    def _comprobar_base_temporal(cls):
        nombre = connection.settings_dict["NAME"]
        if not nombre.startswith(("test_", "vitago_pruebas_concurrencia_")):
            raise RuntimeError("La concurrencia requiere una base exclusiva de pruebas.")
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            if cursor.fetchone()[0] != nombre:
                raise RuntimeError("El destino real no coincide con la base temporal.")

    @classmethod
    def _pre_setup(cls):
        cls._comprobar_base_temporal()
        super()._pre_setup()

    def _fixture_teardown(self):
        self._comprobar_base_temporal()
        super()._fixture_teardown()

    def setUp(self):
        self.base = connection.settings_dict["NAME"]
        pais, _ = Pais.objects.get_or_create(iso2="HN", defaults={
            "iso3": "HND", "nombre": "País de prueba", "codigo_telefonico": "+504",
            "codigo_moneda": "HNL", "zona_horaria_predeterminada": "America/Tegucigalpa",
        })
        self.empresa = Empresa.objects.create(nombre="Empresa de concurrencia", pais=pais)
        self.administrador = Usuario.objetos.create(
            correo="administrador@example.test", nombres="Prueba", apellidos="Concurrencia",
            empresa=self.empresa, es_superusuario=True,
        )
        rol, _ = Rol.objetos.get_or_create(codigo="REPARTIDOR_CORPORATIVO", defaults={
            "nombre": "Motorista de prueba", "permite_alcance_empresa": True,
        })
        permiso, _ = Permiso.objetos.get_or_create(codigo="solicitud.actualizar_estado", defaults={
            "nombre": "Operar solicitudes de prueba",
        })
        PermisoRol.objetos.get_or_create(rol=rol, permiso=permiso)
        tipo = TipoUbicacion.objects.create(codigo="CONCURRENCIA", nombre="Prueba")
        self.ubicaciones = []
        self.sucursales = []
        for indice in range(2):
            ubicacion = Ubicacion.objects.create(
                nombre=f"Sucursal {indice}", tipo_ubicacion=tipo, pais=pais,
                origen="REGISTRADA_USUARIO", localidad="Ciudad de prueba", direccion="Prueba",
                nivel_administrativo_1="Departamento de prueba",
                latitud=Decimal("14.072300") + Decimal(indice) / 100,
                longitud=Decimal("-87.192100"),
            )
            UbicacionEmpresa.objects.create(
                empresa=self.empresa, ubicacion=ubicacion, estado="APROBADO",
                permite_origen=True, permite_destino=True,
            )
            self.ubicaciones.append(ubicacion)
            self.sucursales.append(Sucursal.objects.create(
                empresa=self.empresa, nombre=ubicacion.nombre, ubicacion=ubicacion,
            ))
        self.tipo_servicio = TipoServicio.objects.create(codigo="CONCURRENCIA", nombre="Prueba")
        self.repartidores = []
        for indice in range(2):
            usuario = Usuario.objetos.create(
                correo=f"motorista{indice}@example.test", nombres="Motorista", apellidos=str(indice),
                empresa=self.empresa,
            )
            RolUsuario.objetos.create(usuario=usuario, rol=rol, tipo_alcance="EMPRESA", empresa=self.empresa)
            vehiculo = Vehiculo.objects.create(empresa=self.empresa, placa=f"CON-{indice}", tipo="MOTOCICLETA")
            repartidor = Repartidor.objects.create(
                usuario=usuario, empresa=self.empresa, vehiculo=vehiculo, estado_operativo="AVAILABLE",
            )
            jornada = JornadaRepartidor.objects.create(repartidor=repartidor)
            RegistroUbicacion.objects.create(
                id_cliente=uuid.uuid4(), repartidor=repartidor, jornada=jornada,
                latitud=self.ubicaciones[indice].latitud, longitud=self.ubicaciones[indice].longitud,
                precision_metros=Decimal("8"), registrada_en=timezone.now(),
            )
            self.repartidores.append(repartidor)

    def _post(self, ruta, datos, usuario=None):
        cliente = APIClient()
        cliente.force_authenticate(user=usuario or self.administrador)
        respuesta = cliente.post(f"/api/v1/{ruta}", datos, format="json")
        return respuesta.status_code, respuesta.data

    def _asignar(self, solicitud, repartidor):
        return self._post(f"solicitudes/{solicitud.pk}/asignaciones/", {"repartidor_id": str(repartidor.pk)})

    def _crear(self, prioridad="NORMAL"):
        return self._post("solicitudes/", {
            "cantidad_tubos": 1,
            "empresa_id": str(self.empresa.pk), "sucursal_id": str(self.sucursales[0].pk),
            "origen_id": str(self.ubicaciones[0].pk), "destino_id": str(self.ubicaciones[1].pk),
            "modalidad": "ENTRE_SUCURSALES", "prioridad": prioridad,
            "tipo_servicio_id": str(self.tipo_servicio.pk),
        })

    def _pendiente(self):
        return Solicitud.objects.create(
            cantidad_tubos=1,
            numero=f"CON-{uuid.uuid4().hex[:24]}", empresa=self.empresa,
            solicitada_por=self.administrador, prioridad="NORMAL", modalidad="ENTRE_SUCURSALES",
            origen=self.ubicaciones[0], destino=self.ubicaciones[1], tipo_servicio=self.tipo_servicio,
        )

    def _paralelas(self, acciones, *, sincronizar_motoristas=False):
        barrera = Barrier(len(acciones), timeout=15)
        barrera_motoristas = Barrier(len(acciones), timeout=15)

        def ejecutar(accion):
            primer_bloqueo = True

            def coordinar_bloqueo(ejecutar_sql, sql, parametros, muchos, contexto):
                nonlocal primer_bloqueo
                if sincronizar_motoristas and primer_bloqueo and 'FROM "repartidores"' in sql and 'FOR UPDATE' in sql:
                    # Ambas solicitudes quedan bloqueadas antes de competir por
                    # los motoristas. No sustituir consultas ni sus bloqueos.
                    primer_bloqueo = False
                    barrera_motoristas.wait()
                return ejecutar_sql(sql, parametros, muchos, contexto)

            try:
                propia = connections["default"]
                self.assertEqual(propia.settings_dict["NAME"], self.base)
                with propia.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                    cursor.execute("SET statement_timeout = '20s'")
                    cursor.execute("SELECT current_database(), pg_backend_pid()")
                    base, proceso = cursor.fetchone()
                    self.assertEqual(base, self.base)
                barrera.wait()
                with propia.execute_wrapper(coordinar_bloqueo):
                    return proceso, accion()
            finally:
                connections.close_all()

        with self.assertNoLogs("vitago.api", level="ERROR"):
            with ThreadPoolExecutor(max_workers=len(acciones)) as ejecutor:
                resultados = list(ejecutor.map(ejecutar, acciones))
        self.assertEqual(len({fila[0] for fila in resultados}), len(acciones))
        return [fila[1] for fila in resultados]

    def _comprobar_integridad(self):
        for solicitud in Solicitud.objects.all():
            activas = AsignacionSolicitud.objects.filter(solicitud=solicitud, estado="ACTIVA")
            tiene_asignacion = solicitud.estado in ESTADOS_SOLICITUD_ACTIVOS and solicitud.repartidor_asignado_id is not None
            self.assertEqual(activas.count(), int(tiene_asignacion))
            if tiene_asignacion:
                self.assertEqual(activas.get().repartidor_id, solicitud.repartidor_asignado_id)
        self.assertEqual(
            AsignacionSolicitud.objects.count(),
            EventoSolicitud.objects.filter(tipo__in=("ASIGNADA", "REASIGNADA")).count(),
        )
        self.assertEqual(
            AsignacionSolicitud.objects.count(),
            NotificacionUsuario.objects.filter(tipo__in=(
                TipoNotificacion.SOLICITUD_ASIGNADA, TipoNotificacion.SOLICITUD_REASIGNADA,
                TipoNotificacion.SOLICITUD_PRIORITARIA,
            )).count(),
        )
        for repartidor in self.repartidores:
            repartidor.refresh_from_db()
            cantidad = contar_solicitudes_activas(repartidor)
            self.assertLessEqual(cantidad, 5)
            self.assertEqual(repartidor.capacidad, calcular_capacidad(cantidad, limite_tubos=repartidor.limite_tubos, **obtener_carga_recipientes(repartidor)))
            ruta = RutaRepartidor.objects.filter(repartidor=repartidor, estado="ACTIVA").first()
            paradas = obtener_paradas_operativas(repartidor)
            if ruta is None:
                self.assertFalse(paradas)
            else:
                ultima = ruta.versiones.order_by("-numero").first()
                self.assertEqual(
                    list(ultima.paradas.order_by("orden").values_list("solicitud_id", "tipo")),
                    [(parada["solicitud_id"], parada["tipo"]) for parada in paradas],
                )

    def test_ocho_asignaciones_manuales_no_superan_cinco(self):
        pendientes = [self._pendiente() for _ in range(8)]
        resultados = self._paralelas([
            lambda solicitud=solicitud: self._asignar(solicitud, self.repartidores[0])
            for solicitud in pendientes
        ])
        self.assertEqual(Counter(estado for estado, _ in resultados), {201: 5, 409: 3})
        for estado, datos in resultados:
            if estado == 409:
                self.assertIn("repartidor_id", datos)
        self.assertFalse(listar_repartidores_disponibles(self.administrador).filter(pk=self.repartidores[0].pk).exists())
        self._comprobar_integridad()

    def test_con_cuatro_servicios_solo_uno_de_ocho_obtiene_el_ultimo_cupo(self):
        for _ in range(4):
            asignar_solicitud_manualmente(self.administrador, self._pendiente().pk, {"repartidor_id": self.repartidores[0].pk})
        pendientes = [self._pendiente() for _ in range(8)]
        resultados = self._paralelas([
            lambda solicitud=solicitud: self._asignar(solicitud, self.repartidores[0])
            for solicitud in pendientes
        ])
        self.assertEqual(Counter(estado for estado, _ in resultados), {201: 1, 409: 7})
        self._comprobar_integridad()

    def test_asignaciones_repetidas_a_la_misma_solicitud_no_duplican_avisos(self):
        solicitud = self._pendiente()
        resultados = self._paralelas([lambda: self._asignar(solicitud, self.repartidores[0])] * 8)
        self.assertEqual(Counter(estado for estado, _ in resultados), {201: 1, 400: 7})
        self.assertEqual(AsignacionSolicitud.objects.count(), 1)
        self._comprobar_integridad()

    def test_creaciones_automaticas_concurrentes_respetan_cupo(self):
        Repartidor.objects.filter(pk=self.repartidores[1].pk).update(estado_operativo="PAUSED")
        resultados = self._paralelas([self._crear] * 8)
        self.assertEqual([estado for estado, _ in resultados], [201] * 8)
        # SKIP LOCKED puede dejar pendientes; el evento siguiente las revisa.
        reintentar_solicitudes_pendientes(self.empresa.pk)
        self.assertEqual(Solicitud.objects.filter(estado="ASSIGNED").count(), 5)
        self.assertEqual(Solicitud.objects.filter(estado="PENDING").count(), 3)
        self._comprobar_integridad()

    def test_reintentos_automaticos_simultaneos_no_duplican_asignacion(self):
        self._pendiente()
        self._paralelas([lambda: reintentar_solicitudes_pendientes(self.empresa.pk)] * 8)
        self.assertEqual(AsignacionSolicitud.objects.count(), 1)
        self._comprobar_integridad()

    def _cambio_bloqueado_y_creacion(self, cambiar):
        listo, liberar = Event(), Event()

        def cambiar_con_bloqueo():
            with transaction.atomic():
                repartidor = Repartidor.objects.select_for_update().get(pk=self.repartidores[0].pk)
                cambiar(repartidor)
                listo.set()
                self.assertTrue(liberar.wait(15), "La creación no terminó dentro del plazo.")

        def crear_mientras_esta_bloqueado():
            try:
                self.assertTrue(listo.wait(15), "No se obtuvo el bloqueo del motorista cercano.")
                return self._crear()
            finally:
                liberar.set()

        _, (estado, datos) = self._paralelas([cambiar_con_bloqueo, crear_mientras_esta_bloqueado])
        self.assertEqual(estado, 201)
        solicitud = Solicitud.objects.get(pk=datos["id"])
        self.assertEqual(solicitud.repartidor_asignado_id, self.repartidores[1].pk)
        self._comprobar_integridad()

    def test_prioritario_en_asignacion_bloquea_nuevos_servicios_al_cercano(self):
        prioritaria = self._pendiente()
        prioritaria.prioridad = "PRIORITY"
        prioritaria.save(update_fields=("prioridad",))
        self._cambio_bloqueado_y_creacion(lambda repartidor: asignar_solicitud_manualmente(
            self.administrador, prioritaria.pk, {"repartidor_id": repartidor.pk},
        ))
        self.assertTrue(NotificacionUsuario.objects.filter(solicitud=prioritaria, tipo=TipoNotificacion.SOLICITUD_PRIORITARIA).exists())

    def test_motorista_que_se_pausa_no_recibe_creacion_simultanea(self):
        def pausar(repartidor):
            repartidor.estado_operativo = "PAUSED"
            repartidor.save(update_fields=("estado_operativo",))

        self._cambio_bloqueado_y_creacion(pausar)

    def test_gps_vencido_excluye_al_mas_cercano_con_creaciones_simultaneas(self):
        RegistroUbicacion.objects.filter(repartidor=self.repartidores[0]).update(registrada_en=timezone.now() - timedelta(days=1))
        resultados = self._paralelas([self._crear] * 5)
        self.assertEqual([estado for estado, _ in resultados], [201] * 5)
        reintentar_solicitudes_pendientes(self.empresa.pk)
        self.assertEqual(contar_solicitudes_activas(self.repartidores[0]), 0)
        self.assertEqual(contar_solicitudes_activas(self.repartidores[1]), 5)
        self._comprobar_integridad()

    def _cierre_y_creacion(self, estado_destino):
        Repartidor.objects.filter(pk=self.repartidores[1].pk).update(estado_operativo="PAUSED")
        solicitudes = [self._pendiente() for _ in range(5)]
        for solicitud in solicitudes:
            asignar_solicitud_manualmente(self.administrador, solicitud.pk, {"repartidor_id": self.repartidores[0].pk})
        cerrada = solicitudes[0]
        if estado_destino == "DELIVERED":
            Solicitud.objects.filter(pk=cerrada.pk).update(estado="AT_DESTINATION")
            # Fixture de evidencia ya registrada; esta prueba no simula archivos.
            EvidenciaSolicitud.objects.create(
                solicitud=cerrada, repartidor=self.repartidores[0], tipo=TipoEvidenciaSolicitud.FOTO_ENTREGA,
                clave_almacenamiento=f"pruebas/{uuid.uuid4()}.jpg", tipo_contenido="image/jpeg", tamano_bytes=100,
                latitud=self.ubicaciones[1].latitud, longitud=self.ubicaciones[1].longitud, capturada_en=timezone.now(),
            )

        def cerrar():
            return self._post(f"solicitudes/{cerrada.pk}/transiciones/", {
                "estado_destino": estado_destino, "motivo": "Cierre sintético de prueba",
            }, usuario=self.administrador if estado_destino == "CANCELLED" else self.repartidores[0].usuario)

        resultados = self._paralelas([cerrar, self._crear])
        self.assertEqual([estado for estado, _ in resultados], [200, 201])
        reintentar_solicitudes_pendientes(self.empresa.pk)
        cerrada.refresh_from_db()
        self.assertEqual(cerrada.estado, estado_destino)
        self.assertEqual(contar_solicitudes_activas(self.repartidores[0]), 5)
        self._comprobar_integridad()

    def test_cancelacion_y_creacion_simultaneas_liberan_un_solo_cupo(self):
        self._cierre_y_creacion("CANCELLED")

    def test_entrega_y_creacion_simultaneas_liberan_un_solo_cupo(self):
        self._cierre_y_creacion("DELIVERED")

    def test_reasignaciones_cruzadas_no_bloquean_y_conservan_historial(self):
        solicitudes = [self._pendiente(), self._pendiente()]
        for solicitud, repartidor in zip(solicitudes, self.repartidores):
            asignar_solicitud_manualmente(self.administrador, solicitud.pk, {"repartidor_id": repartidor.pk})
        resultados = self._paralelas([
            lambda: self._asignar(solicitudes[0], self.repartidores[1]),
            lambda: self._asignar(solicitudes[1], self.repartidores[0]),
        ], sincronizar_motoristas=True)
        self.assertEqual([estado for estado, _ in resultados], [201, 201])
        self.assertEqual(AsignacionSolicitud.objects.filter(estado="REASIGNADA").count(), 2)
        self.assertEqual(NotificacionUsuario.objects.filter(tipo=TipoNotificacion.SOLICITUD_RETIRADA).count(), 2)
        self._comprobar_integridad()

    def _dos_asignadas_al_mismo_motorista(self):
        solicitudes = [self._pendiente(), self._pendiente()]
        for solicitud in solicitudes:
            asignar_solicitud_manualmente(self.administrador, solicitud.pk, {"repartidor_id": self.repartidores[0].pk})
        return solicitudes

    def test_cancelaciones_simultaneas_no_bloquean_referencias_de_ruta(self):
        solicitudes = self._dos_asignadas_al_mismo_motorista()
        resultados = self._paralelas([
            lambda solicitud=solicitud: self._post(f"solicitudes/{solicitud.pk}/transiciones/", {
                "estado_destino": "CANCELLED", "motivo": "Cancelación sintética",
            }) for solicitud in solicitudes
        ], sincronizar_motoristas=True)
        self.assertEqual([estado for estado, _ in resultados], [200, 200])
        self.assertEqual(Solicitud.objects.filter(estado="CANCELLED").count(), 2)
        self._comprobar_integridad()

    def test_cierres_diarios_simultaneos_no_bloquean_referencias_de_ruta(self):
        solicitudes = self._dos_asignadas_al_mismo_motorista()
        # Solo fixtures de la base temporal; no ejecutar el comando/tarea real.
        Solicitud.objects.all().update(creado_en=timezone.now() - timedelta(days=1))
        resultados = self._paralelas([
            lambda solicitud=solicitud: cerrar_solicitud_vencida(solicitud.pk)
            for solicitud in solicitudes
        ], sincronizar_motoristas=True)
        self.assertEqual(resultados, [True, True])
        self.assertEqual(Solicitud.objects.filter(estado="PICKUP_FAILED", motivo_cierre="FIN_DIA").count(), 2)
        self._comprobar_integridad()

    def test_retiros_simultaneos_por_suspension_no_bloquean_rutas(self):
        solicitudes = self._dos_asignadas_al_mismo_motorista()
        Usuario.objetos.filter(pk=self.repartidores[0].usuario_id).update(estado="SUSPENDIDO")
        resultados = self._paralelas([
            lambda solicitud=solicitud: retirar_servicio_por_suspension(solicitud.pk, self.administrador)
            for solicitud in solicitudes
        ], sincronizar_motoristas=True)
        self.assertEqual(resultados, [True, True])
        reintentar_solicitudes_pendientes(self.empresa.pk)
        self.assertEqual(contar_solicitudes_activas(self.repartidores[0]), 0)
        self.assertEqual(contar_solicitudes_activas(self.repartidores[1]), 2)
        self._comprobar_integridad()

    def test_dos_asignaciones_compiten_por_los_ultimos_dos_tubos(self):
        inicial = self._pendiente()
        Solicitud.objects.filter(pk=inicial.pk).update(cantidad_tubos=18)
        self.assertEqual(self._asignar(inicial, self.repartidores[0])[0], 201)
        solicitudes = [self._pendiente(), self._pendiente()]
        Solicitud.objects.filter(pk__in=[s.pk for s in solicitudes]).update(cantidad_tubos=2)
        resultados = self._paralelas([
            lambda s=s: self._asignar(s, self.repartidores[0]) for s in solicitudes
        ], sincronizar_motoristas=True)
        self.assertEqual(sorted(estado for estado, _ in resultados), [201, 409])
        from apps.repartidores.capacidad import obtener_carga_recipientes
        self.assertEqual(obtener_carga_recipientes(self.repartidores[0])["tubos_comprometidos"], 20)
        self._comprobar_integridad()
