import uuid
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from apps.flota.models import Vehiculo
from apps.geografia.models import Pais
from apps.jornadas.models import JornadaRepartidor
from apps.organizaciones.models import Empresa, Sucursal
from apps.repartidores.models import Repartidor
from apps.seguimiento.servicios import registrar_ubicaciones
from apps.solicitudes.models import AsignacionSolicitud, Solicitud, TipoServicio
from apps.solicitudes.opciones import (
    EstadoAsignacionSolicitud,
    EstadoSolicitud,
    ModalidadSolicitud,
    PrioridadSolicitud,
)
from apps.solicitudes.servicios import crear_solicitud
from apps.solicitudes.selectores import (
    obtener_opciones_creacion_solicitud,
    resumir_solicitudes_autorizadas,
)
from apps.solicitudes.servicios_movimientos import (
    cerrar_movimiento_especial,
    iniciar_movimiento_especial,
)
from apps.ubicaciones.models import TipoUbicacion, Ubicacion, UbicacionEmpresa
from apps.ubicaciones.opciones import (
    EstadoUbicacionEmpresa,
    OrigenUbicacion,
)
from apps.usuarios.models import Rol, RolUsuario, Usuario
from apps.usuarios.opciones import TipoAlcanceRol


@override_settings(
    MODO_APLICACION="CORPORATIVO",
    PROVEEDOR_AUTENTICACION="LOCAL",
    PRECISION_GPS_MAXIMA_METROS=100,
    VELOCIDAD_GPS_MAXIMA_METROS_SEGUNDO=55,
)
class PruebasModalidadesCorporativas(TestCase):
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
        cls.tipo_sucursal = TipoUbicacion.objects.get(codigo="SUCURSAL")
        cls.tipo_transporte = TipoUbicacion.objects.get(
            codigo="EMPRESA_TRANSPORTE"
        )
        cls.origen = cls._crear_ubicacion(
            "Sucursal Centro", cls.tipo_sucursal, "Tegucigalpa", "14.000000"
        )
        cls.destino = cls._crear_ubicacion(
            "Sucursal Norte", cls.tipo_sucursal, "Tegucigalpa", "14.010000"
        )
        cls.destino_otra_ciudad = cls._crear_ubicacion(
            "Sucursal San Pedro", cls.tipo_sucursal, "San Pedro Sula", "15.500000"
        )
        cls.empresa_transporte = cls._crear_ubicacion(
            "Transportes Centroamericanos",
            cls.tipo_transporte,
            "Tegucigalpa",
            "14.020000",
        )
        cls.sucursal_origen = Sucursal.objects.create(
            empresa=cls.empresa,
            nombre="Centro",
            ubicacion=cls.origen,
        )
        Sucursal.objects.create(
            empresa=cls.empresa,
            nombre="Norte",
            ubicacion=cls.destino,
        )
        Sucursal.objects.create(
            empresa=cls.empresa,
            nombre="San Pedro",
            ubicacion=cls.destino_otra_ciudad,
        )
        for ubicacion in (
            cls.origen,
            cls.destino,
            cls.destino_otra_ciudad,
            cls.empresa_transporte,
        ):
            UbicacionEmpresa.objects.create(
                empresa=cls.empresa,
                ubicacion=ubicacion,
                permite_origen=ubicacion == cls.origen,
                permite_destino=ubicacion != cls.origen,
                estado=EstadoUbicacionEmpresa.APROBADO,
            )
        cls.tipo_servicio = TipoServicio.objects.create(
            codigo="MENSAJERIA_INTERNA",
            nombre="Mensajería interna",
        )
        cls.administrador = Usuario.objetos.create(
            correo="admin.modalidades@analiza.test",
            nombres="Admin",
            apellidos="Pruebas",
            empresa=cls.empresa,
            es_superusuario=True,
        )
        cls.gerente = cls._crear_usuario_con_rol(
            "gerente.operaciones@analiza.test", "GERENTE_OPERACIONES"
        )
        cls.solicitante = cls._crear_usuario_con_rol(
            "solicitante.sucursal@analiza.test", "SOLICITANTE_CORPORATIVO"
        )
        cls.usuario_repartidor = cls._crear_usuario_con_rol(
            "motorista.especial@analiza.test", "REPARTIDOR_CORPORATIVO"
        )
        cls.vehiculo = Vehiculo.objects.create(
            empresa=cls.empresa,
            placa="ESP-001",
            tipo="MOTOCICLETA",
        )
        cls.repartidor = Repartidor.objects.create(
            usuario=cls.usuario_repartidor,
            empresa=cls.empresa,
            vehiculo=cls.vehiculo,
        )

    @classmethod
    def _crear_ubicacion(cls, nombre, tipo, ciudad, latitud):
        return Ubicacion.objects.create(
            nombre=nombre,
            tipo_ubicacion=tipo,
            origen=OrigenUbicacion.REGISTRADA_USUARIO,
            pais=cls.pais,
            localidad=ciudad,
            direccion=f"Dirección de {nombre}",
            latitud=Decimal(latitud),
            longitud=Decimal("-87.000000"),
        )

    @classmethod
    def _crear_usuario_con_rol(cls, correo, codigo_rol):
        usuario = Usuario.objetos.create(
            correo=correo,
            nombres="Usuario",
            apellidos=codigo_rol,
            empresa=cls.empresa,
        )
        RolUsuario.objetos.create(
            usuario=usuario,
            rol=Rol.objetos.get(codigo=codigo_rol),
            tipo_alcance=TipoAlcanceRol.EMPRESA,
            empresa=cls.empresa,
            asignado_por=cls.administrador,
        )
        return usuario

    def _datos_creacion(self, modalidad, **cambios):
        datos = {
            "empresa_id": self.empresa.id,
            "sucursal_id": self.sucursal_origen.id,
            "prioridad": PrioridadSolicitud.NORMAL,
            "modalidad": modalidad,
            "tipo_servicio_id": self.tipo_servicio.id,
            "origen_id": self.origen.id,
            "destino_id": self.destino.id,
            "articulos": [{"tipo_articulo": "Documentos", "cantidad": 1}],
        }
        datos.update(cambios)
        return datos

    def test_solo_gerente_operaciones_crea_envio_especial(self):
        datos = self._datos_creacion(
            ModalidadSolicitud.ESPECIAL,
            destino_id=None,
            destino_especial="Oficinas centrales del proveedor",
        )

        with self.assertRaises(PermissionDenied):
            crear_solicitud(self.solicitante, datos)

        solicitud = crear_solicitud(self.gerente, datos)
        self.assertIsNone(solicitud.destino_id)
        self.assertEqual(
            solicitud.destino_especial,
            "Oficinas centrales del proveedor",
        )

    def test_rechaza_modalidad_abierta_en_corporativo(self):
        with self.assertRaises(ValidationError):
            crear_solicitud(
                self.gerente,
                self._datos_creacion(ModalidadSolicitud.ABIERTO),
            )

    def test_traslado_entre_sucursales_exige_misma_ciudad(self):
        with self.assertRaises(ValidationError):
            crear_solicitud(
                self.gerente,
                self._datos_creacion(
                    ModalidadSolicitud.ENTRE_SUCURSALES,
                    destino_id=self.destino_otra_ciudad.id,
                ),
            )

    def test_empresa_transporte_exige_tipo_de_ubicacion_correcto(self):
        solicitud = crear_solicitud(
            self.gerente,
            self._datos_creacion(
                ModalidadSolicitud.EMPRESA_TRANSPORTE,
                destino_id=self.empresa_transporte.id,
            ),
        )

        self.assertEqual(
            solicitud.destino.tipo_ubicacion.codigo,
            "EMPRESA_TRANSPORTE",
        )

    def test_movimiento_asocia_gps_y_congela_kilometros(self):
        ahora = timezone.now()
        jornada = JornadaRepartidor.objects.create(
            repartidor=self.repartidor,
            iniciada_en=ahora - timedelta(minutes=10),
        )
        solicitud = Solicitud.objects.create(
            numero=f"SOL-ESP-{uuid.uuid4().hex[:8]}",
            empresa=self.empresa,
            sucursal=self.sucursal_origen,
            solicitada_por=self.gerente,
            repartidor_asignado=self.repartidor,
            prioridad=PrioridadSolicitud.NORMAL,
            modalidad=ModalidadSolicitud.ESPECIAL,
            tipo_servicio=self.tipo_servicio,
            origen=self.origen,
            destino=None,
            destino_especial="Destino excepcional",
        )
        AsignacionSolicitud.objects.create(
            solicitud=solicitud,
            repartidor=self.repartidor,
            asignada_por=self.gerente,
            estado=EstadoAsignacionSolicitud.ACTIVA,
            asignada_en=ahora - timedelta(minutes=6),
            aceptada_en=ahora - timedelta(minutes=5),
        )
        movimiento = iniciar_movimiento_especial(
            solicitud,
            self.repartidor,
            latitud=Decimal("14.000000"),
            longitud=Decimal("-87.000000"),
            ahora=ahora - timedelta(minutes=4),
        )
        registros = [
            {
                "id_cliente": uuid.uuid4(),
                "latitud": Decimal("14.001000"),
                "longitud": Decimal("-87.000000"),
                "precision_metros": Decimal("10"),
                "velocidad_metros_segundo": Decimal("3"),
                "rumbo_grados": None,
                "registrada_en": ahora - timedelta(minutes=3),
            },
            {
                "id_cliente": uuid.uuid4(),
                "latitud": Decimal("14.001500"),
                "longitud": Decimal("-87.000000"),
                "precision_metros": Decimal("500"),
                "velocidad_metros_segundo": Decimal("3"),
                "rumbo_grados": None,
                "registrada_en": ahora - timedelta(minutes=2),
            },
        ]
        resultado = registrar_ubicaciones(
            self.usuario_repartidor,
            {"jornada_id": jornada.id, "registros": registros},
        )

        cerrado = cerrar_movimiento_especial(
            solicitud,
            self.repartidor,
            latitud=Decimal("14.002000"),
            longitud=Decimal("-87.000000"),
            ahora=ahora,
        )

        self.assertTrue(
            all(
                registro.movimiento_envio_especial_id == movimiento.id
                for registro in resultado["registros"]
            )
        )
        self.assertEqual(cerrado.registros_considerados, 1)
        self.assertEqual(cerrado.registros_descartados, 1)
        self.assertGreater(cerrado.kilometros_recorridos, Decimal("0.200"))
        self.assertLess(cerrado.kilometros_recorridos, Decimal("0.250"))

    def test_opciones_filtran_destinos_y_ocultan_especial_sin_permiso(self):
        opciones = obtener_opciones_creacion_solicitud(
            self.solicitante,
            {
                "empresa_id": self.empresa.id,
                "modalidad": ModalidadSolicitud.ENTRE_SUCURSALES,
                "origen_id": self.origen.id,
            },
        )

        codigos = {modalidad["codigo"] for modalidad in opciones["modalidades"]}
        destinos = {
            punto["ubicacion"].id for punto in opciones["destinos"]
        }
        self.assertNotIn(ModalidadSolicitud.ESPECIAL, codigos)
        self.assertIn(self.destino.id, destinos)
        self.assertNotIn(self.destino_otra_ciudad.id, destinos)

    def test_opciones_entre_sucursales_permiten_elegir_modalidad_antes_del_origen(self):
        cliente = APIClient()
        cliente.force_authenticate(self.solicitante)
        ruta = reverse("solicitudes:opciones-creacion")
        base = {
            "empresa_id": str(self.empresa.id),
            "modalidad": ModalidadSolicitud.ENTRE_SUCURSALES,
        }
        inicial = cliente.get(ruta, base)
        self.assertEqual(inicial.status_code, 200)
        self.assertGreaterEqual(len(inicial.data["origenes"]), 1)
        self.assertEqual(inicial.data["destinos"], [])
        self.assertIsNone(inicial.data["mensaje_disponibilidad"])

        con_sucursal = cliente.get(
            ruta, {**base, "sucursal_id": str(self.sucursal_origen.id)}
        )
        self.assertEqual(con_sucursal.status_code, 200)
        self.assertEqual(len(con_sucursal.data["destinos"]), 1)
        self.assertIsNone(con_sucursal.data["mensaje_disponibilidad"])

        con_id_de_sucursal = cliente.get(
            ruta, {**base, "origen_id": str(self.sucursal_origen.id)}
        )
        self.assertEqual(con_id_de_sucursal.status_code, 200)
        self.assertEqual(len(con_id_de_sucursal.data["destinos"]), 1)

    def test_opciones_sin_sucursales_devuelven_mensaje_sin_error(self):
        UbicacionEmpresa.objects.filter(empresa=self.empresa).update(
            permite_origen=False
        )
        cliente = APIClient()
        cliente.force_authenticate(self.solicitante)

        respuesta = cliente.get(
            reverse("solicitudes:opciones-creacion"),
            {
                "empresa_id": str(self.empresa.id),
                "modalidad": ModalidadSolicitud.ENTRE_SUCURSALES,
            },
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data["origenes"], [])
        self.assertEqual(respuesta.data["destinos"], [])
        self.assertEqual(
            respuesta.data["mensaje_disponibilidad"],
            "No hay sucursales disponibles para crear solicitudes.",
        )

    def test_opciones_sin_destinos_devuelven_mensaje_sin_error(self):
        UbicacionEmpresa.objects.filter(
            empresa=self.empresa,
            ubicacion=self.destino,
        ).update(permite_destino=False)
        cliente = APIClient()
        cliente.force_authenticate(self.solicitante)

        respuesta = cliente.get(
            reverse("solicitudes:opciones-creacion"),
            {
                "empresa_id": str(self.empresa.id),
                "modalidad": ModalidadSolicitud.ENTRE_SUCURSALES,
                "origen_id": str(self.origen.id),
            },
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(len(respuesta.data["origenes"]), 1)
        self.assertEqual(respuesta.data["destinos"], [])
        self.assertEqual(
            respuesta.data["mensaje_disponibilidad"],
            "No hay sucursales de destino disponibles en la misma ciudad.",
        )

    def test_opciones_no_ocultan_origen_invalido_como_lista_vacia(self):
        cliente = APIClient()
        cliente.force_authenticate(self.solicitante)

        respuesta = cliente.get(
            reverse("solicitudes:opciones-creacion"),
            {
                "empresa_id": str(self.empresa.id),
                "modalidad": ModalidadSolicitud.ENTRE_SUCURSALES,
                "origen_id": str(uuid.uuid4()),
            },
        )

        self.assertEqual(respuesta.status_code, 404)

    def test_gerente_recibe_modalidad_especial_sin_destinos(self):
        opciones = obtener_opciones_creacion_solicitud(
            self.gerente,
            {
                "empresa_id": self.empresa.id,
                "modalidad": ModalidadSolicitud.ESPECIAL,
            },
        )

        codigos = {modalidad["codigo"] for modalidad in opciones["modalidades"]}
        self.assertIn(ModalidadSolicitud.ESPECIAL, codigos)
        self.assertTrue(opciones["puede_crear_envio_especial"])
        self.assertEqual(opciones["destinos"], [])

    def test_resumen_solicitante_solo_cuenta_solicitudes_propias(self):
        for indice, estado in enumerate(
            (
                EstadoSolicitud.PENDIENTE,
                EstadoSolicitud.EN_TRANSITO,
                EstadoSolicitud.ENTREGADA,
            ),
            start=1,
        ):
            Solicitud.objects.create(
                numero=f"SOL-RESUMEN-{indice}",
                empresa=self.empresa,
                sucursal=self.sucursal_origen,
                solicitada_por=self.solicitante,
                prioridad=PrioridadSolicitud.NORMAL,
                modalidad=ModalidadSolicitud.ENTRE_SUCURSALES,
                tipo_servicio=self.tipo_servicio,
                origen=self.origen,
                destino=self.destino,
                estado=estado,
            )
        Solicitud.objects.create(
            numero="SOL-RESUMEN-AJENA",
            empresa=self.empresa,
            sucursal=self.sucursal_origen,
            solicitada_por=self.gerente,
            prioridad=PrioridadSolicitud.NORMAL,
            modalidad=ModalidadSolicitud.ENTRE_SUCURSALES,
            tipo_servicio=self.tipo_servicio,
            origen=self.origen,
            destino=self.destino,
        )

        conteos, recientes = resumir_solicitudes_autorizadas(
            self.solicitante,
            {"empresa_id": self.empresa.id},
        )

        self.assertEqual(conteos["total"], 3)
        self.assertEqual(conteos["pendientes"], 1)
        self.assertEqual(conteos["activas"], 1)
        self.assertEqual(conteos["entregadas"], 1)
        self.assertEqual(len(recientes), 3)

    def test_api_opciones_y_resumen_responden_contrato(self):
        cliente = APIClient()
        cliente.force_authenticate(self.gerente)

        respuesta_opciones = cliente.get(
            reverse("solicitudes:opciones-creacion"),
            {
                "empresa_id": str(self.empresa.id),
                "modalidad": ModalidadSolicitud.EMPRESA_TRANSPORTE,
            },
        )
        respuesta_resumen = cliente.get(
            reverse("solicitudes:resumen-solicitante"),
            {"empresa_id": str(self.empresa.id)},
        )

        self.assertEqual(respuesta_opciones.status_code, 200)
        self.assertEqual(
            respuesta_opciones.data["destinos"][0]["ubicacion"]["tipo_codigo"],
            "EMPRESA_TRANSPORTE",
        )
        self.assertEqual(respuesta_resumen.status_code, 200)
        self.assertIn("recientes", respuesta_resumen.data)
