"""Resumen diario por fecha de entrega, permisos y límites de zona horaria."""

from datetime import datetime, timedelta, timezone as zona_utc
from decimal import Decimal
from unittest.mock import patch
import uuid

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.geografia.models import Pais
from apps.organizaciones.models import Empresa, Sucursal
from apps.solicitudes.models import Solicitud
from apps.solicitudes.opciones import EstadoSolicitud
from apps.solicitudes.selectores import resumir_solicitudes_autorizadas
from apps.ubicaciones.models import TipoUbicacion, Ubicacion
from apps.ubicaciones.opciones import OrigenUbicacion
from apps.usuarios.models import Permiso, PermisoRol, Rol, RolUsuario, Usuario
from apps.usuarios.opciones import TipoAlcanceRol


@override_settings(
    MODO_APLICACION="CORPORATIVO",
    TIME_ZONE="UTC",
    ZONA_HORARIA_RESUMEN_SOLICITANTE="America/Tegucigalpa",
)
class PruebasResumenDiarioSolicitante(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pais = Pais.objects.create(
            iso2="HN", iso3="HND", nombre="Honduras",
            codigo_telefonico="+504", codigo_moneda="HNL",
            zona_horaria_predeterminada="America/Tegucigalpa",
        )
        cls.empresa = Empresa.objects.create(nombre="Analiza", pais=cls.pais)
        cls.otra_empresa = Empresa.objects.create(nombre="Otra", pais=cls.pais)
        cls.origen = Ubicacion.objects.create(
            nombre="Origen", tipo_ubicacion=TipoUbicacion.objects.get(codigo="SUCURSAL"),
            origen=OrigenUbicacion.REGISTRADA_USUARIO, pais=cls.pais,
            direccion="Dirección de prueba", latitud=Decimal("14.000000"),
            longitud=Decimal("-87.000000"),
        )
        cls.sucursal = Sucursal.objects.create(
            empresa=cls.empresa, nombre="Centro", ubicacion=cls.origen,
        )
        cls.otra_sucursal = Sucursal.objects.create(
            empresa=cls.empresa, nombre="Norte", ubicacion=cls.origen,
        )
        cls.administrador = Usuario.objetos.create(
            correo="admin.resumen@analiza.test", nombres="Admin", apellidos="Prueba",
            es_superusuario=True,
        )
        cls.solicitante = cls._crear_usuario("propio", "SOLICITANTE_CORPORATIVO")
        cls.otro_solicitante = cls._crear_usuario("otro", "SOLICITANTE_CORPORATIVO")
        cls.gerente = cls._crear_usuario("gerente", "GERENTE_OPERACIONES")
        rol_sucursal = Rol.objetos.create(
            codigo="PRUEBA_ADMIN_RESUMEN", nombre="Consulta administrativa de sucursal",
            permite_alcance_sucursal=True,
        )
        PermisoRol.objetos.create(
            rol=rol_sucursal, permiso=Permiso.objetos.get(codigo="solicitud.ver"),
        )
        cls.administrador_sucursal = cls._crear_usuario(
            "admin.sucursal", rol_sucursal.codigo,
            tipo_alcance=TipoAlcanceRol.SUCURSAL,
            sucursal=cls.sucursal,
        )
        cls.sin_permisos = Usuario.objetos.create(
            correo="sin.permisos@analiza.test", nombres="Sin", apellidos="Permisos",
            empresa=cls.empresa,
        )

    @classmethod
    def _crear_usuario(cls, correo, rol_codigo, **alcance):
        usuario = Usuario.objetos.create(
            correo=f"{correo}.resumen@analiza.test", nombres=correo, apellidos="Prueba",
            empresa=cls.empresa,
        )
        RolUsuario.objetos.create(
            usuario=usuario, rol=Rol.objetos.get(codigo=rol_codigo),
            empresa=cls.empresa,
            tipo_alcance=alcance.pop("tipo_alcance", TipoAlcanceRol.EMPRESA),
            asignado_por=cls.administrador, **alcance,
        )
        return usuario

    def setUp(self):
        self.cliente = APIClient()
        self.cliente.force_authenticate(self.solicitante)
        self.url = reverse("solicitudes:resumen-solicitante")
        self.ahora = datetime(2026, 10, 23, 2, 0, tzinfo=zona_utc.utc)
        self.inicio = datetime(2026, 10, 22, 6, 0, tzinfo=zona_utc.utc)

    def _crear_solicitud(self, entregada_en=None, **campos):
        datos = {
            "numero": f"SOL-RES-{Solicitud.objects.count() + 1}",
            "empresa": self.empresa,
            "sucursal": self.sucursal,
            "solicitada_por": self.solicitante,
            "prioridad": "NORMAL", "origen": self.origen, "destino": self.origen,
            "estado": EstadoSolicitud.ENTREGADA,
            "entregada_en": entregada_en,
        }
        datos.update(campos)
        return Solicitud.objects.create(**datos)

    def _consultar(self, filtros=None):
        with patch("apps.solicitudes.selectores.timezone.now", return_value=self.ahora):
            return self.cliente.get(self.url, filtros or {})

    def test_hoy_utiliza_reloj_servidor_y_dia_de_tegucigalpa_no_utc(self):
        respuesta = self._consultar()
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data["fecha_operativa"], "2026-10-22")
        self.assertEqual(respuesta.data["zona_horaria_operativa"], "America/Tegucigalpa")
        self.assertEqual(respuesta.data["entregadas_del_dia"], 0)
        self.assertEqual(respuesta.data["entregas_recientes_del_dia"], [])

    def test_rango_incluye_inicio_excluye_siguiente_y_filtra_estado_y_fecha_entrega(self):
        self._crear_solicitud(self.inicio - timedelta(microseconds=1))
        primera = self._crear_solicitud(self.inicio)
        medianoche_utc = self._crear_solicitud(self.inicio + timedelta(hours=18))
        ultima = self._crear_solicitud(self.inicio + timedelta(days=1, microseconds=-1))
        self._crear_solicitud(self.inicio + timedelta(days=1))
        self._crear_solicitud()
        self._crear_solicitud(self.inicio, estado=EstadoSolicitud.ENTREGA_FALLIDA)
        Solicitud.objects.filter(pk=primera.pk).update(
            creado_en=self.inicio - timedelta(days=3),
        )

        respuesta = self._consultar()

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data["total"], 7)
        self.assertEqual(respuesta.data["entregadas"], 6)
        self.assertEqual(respuesta.data["entregadas_del_dia"], 3)
        self.assertEqual(
            [dato["id"] for dato in respuesta.data["entregas_recientes_del_dia"]],
            [str(ultima.pk), str(medianoche_utc.pk), str(primera.pk)],
        )
        self.assertTrue(all(dato["entregada_en"] for dato in respuesta.data["entregas_recientes_del_dia"]))

    def test_fecha_explicita_consulta_historia_sin_alterar_conteos_acumulados(self):
        anterior = self._crear_solicitud(self.inicio - timedelta(hours=1))
        self._crear_solicitud(self.inicio)
        respuesta = self._consultar({"fecha_operativa": "2026-10-21"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data["fecha_operativa"], "2026-10-21")
        self.assertEqual(respuesta.data["total"], 2)
        self.assertEqual(respuesta.data["entregadas"], 2)
        self.assertEqual(respuesta.data["entregadas_del_dia"], 1)
        self.assertEqual(respuesta.data["entregas_recientes_del_dia"][0]["id"], str(anterior.pk))

    def test_fechas_invalidas_responden_400_asociado_al_campo(self):
        for valor in ("", "ayer", "2026-02-30", "2026-10-22T00:00:00Z", "9999-12-31", "2026-1-2"):
            with self.subTest(fecha=valor):
                respuesta = self._consultar({"fecha_operativa": valor})
                self.assertEqual(respuesta.status_code, 400)
                self.assertIn("fecha_operativa", respuesta.data)

    def test_solicitante_solo_obtiene_entregas_propias(self):
        propia = self._crear_solicitud(self.inicio)
        self._crear_solicitud(self.inicio, solicitada_por=self.otro_solicitante)
        self._crear_solicitud(self.inicio, empresa=self.otra_empresa, sucursal=None)
        respuesta = self._consultar()
        self.assertEqual(respuesta.data["total"], 1)
        self.assertEqual(respuesta.data["entregadas_del_dia"], 1)
        self.assertEqual(respuesta.data["entregas_recientes_del_dia"][0]["id"], str(propia.pk))

    def test_administrador_global_ve_entregas_de_todos_y_respeta_filtros(self):
        self._crear_solicitud(self.inicio)
        self._crear_solicitud(self.inicio, solicitada_por=self.otro_solicitante, sucursal=self.otra_sucursal)
        self._crear_solicitud(self.inicio, empresa=self.otra_empresa, sucursal=None)
        self.cliente.force_authenticate(self.administrador)
        self.assertEqual(self._consultar().data["entregadas_del_dia"], 3)
        self.assertEqual(self._consultar({"empresa_id": str(self.empresa.pk)}).data["entregadas_del_dia"], 2)
        self.assertEqual(self._consultar({"sucursal_id": str(self.sucursal.pk)}).data["entregadas_del_dia"], 1)

    def test_administracion_de_empresa_y_sucursal_no_amplia_alcance(self):
        self._crear_solicitud(self.inicio)
        self._crear_solicitud(self.inicio, solicitada_por=self.otro_solicitante, sucursal=self.otra_sucursal)
        self._crear_solicitud(self.inicio, empresa=self.otra_empresa, sucursal=None)
        for usuario, esperado in ((self.gerente, 2), (self.administrador_sucursal, 1)):
            with self.subTest(usuario=usuario.correo):
                self.cliente.force_authenticate(usuario)
                respuesta = self._consultar()
                self.assertEqual(respuesta.status_code, 200)
                self.assertEqual(respuesta.data["entregadas_del_dia"], esperado)
                fuera = self._consultar({"empresa_id": str(self.otra_empresa.pk)})
                self.assertEqual(fuera.data["entregadas_del_dia"], 0)
                self.assertEqual(fuera.data["entregas_recientes_del_dia"], [])

    def test_recientes_diarias_maximo_cinco_ordenadas_por_entrega_y_uuid(self):
        solicitudes = [
            self._crear_solicitud(self.inicio + timedelta(hours=indice), id=uuid.UUID(int=indice))
            for indice in range(1, 7)
        ]
        desempate = self._crear_solicitud(self.inicio + timedelta(hours=6), id=uuid.UUID(int=7))
        respuesta = self._consultar()
        self.assertEqual(respuesta.data["entregadas_del_dia"], 7)
        self.assertEqual(
            [dato["id"] for dato in respuesta.data["entregas_recientes_del_dia"]],
            [str(s.pk) for s in (desempate, *reversed(solicitudes[2:]))],
        )

    def test_recientes_y_funcion_acumulada_anterior_conservan_contrato(self):
        antigua_entregada_hoy = self._crear_solicitud(self.inicio)
        Solicitud.objects.filter(pk=antigua_entregada_hoy.pk).update(creado_en=self.inicio - timedelta(days=7))
        mas_nuevas = [self._crear_solicitud(estado=EstadoSolicitud.PENDIENTE) for _ in range(5)]
        respuesta = self._consultar()
        self.assertEqual(len(respuesta.data["recientes"]), 5)
        self.assertEqual({dato["id"] for dato in respuesta.data["recientes"]}, {str(s.pk) for s in mas_nuevas})
        self.assertEqual(respuesta.data["entregas_recientes_del_dia"][0]["id"], str(antigua_entregada_hoy.pk))
        conteos, recientes = resumir_solicitudes_autorizadas(self.solicitante)
        self.assertEqual(set(conteos), {"total", "pendientes", "activas", "entregadas", "fallidas", "canceladas"})
        self.assertEqual(conteos["total"], 6)
        self.assertEqual(len(recientes), 5)

    def test_falta_de_permiso_no_expone_conteos_y_anonimo_requiere_autenticacion(self):
        self._crear_solicitud(self.inicio)
        self.cliente.force_authenticate(self.sin_permisos)
        self.assertEqual(self._consultar().status_code, 403)
        self.cliente.force_authenticate(None)
        self.assertEqual(self._consultar().status_code, 401)

    @override_settings(ZONA_HORARIA_RESUMEN_SOLICITANTE="America/Guatemala")
    def test_zona_es_configurable_por_despliegue_sin_cambiar_timezone_general(self):
        respuesta = self._consultar()
        self.assertEqual(respuesta.data["zona_horaria_operativa"], "America/Guatemala")
        self.assertEqual(respuesta.data["fecha_operativa"], "2026-10-22")

    def test_filtros_fuera_del_alcance_no_revelan_actividad(self):
        self._crear_solicitud(self.inicio)
        respuesta = self._consultar({"sucursal_id": str(uuid.uuid4())})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data["total"], 0)
        self.assertEqual(respuesta.data["entregadas_del_dia"], 0)
        self.assertEqual(respuesta.data["recientes"], [])
        self.assertEqual(respuesta.data["entregas_recientes_del_dia"], [])
