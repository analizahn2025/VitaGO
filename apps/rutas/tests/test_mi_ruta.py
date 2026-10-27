"""Contrato, orden y autorización de la ruta operativa provisional."""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.geografia.models import Pais
from apps.jornadas.models import JornadaRepartidor
from apps.organizaciones.models import Empresa
from apps.repartidores.models import Repartidor
from apps.rutas.models import ParadaVersionRuta, RutaRepartidor, VersionRuta
from apps.rutas.selectores import obtener_mi_ruta
from apps.rutas.servicios import sincronizar_ruta
from apps.solicitudes.models import AsignacionSolicitud, Solicitud, TipoServicio
from apps.solicitudes.opciones import (
    EstadoAsignacionSolicitud,
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
class PruebasMiRuta(TestCase):
    @classmethod
    def setUpTestData(cls):
        pais = Pais.objects.create(
            iso2="HN",
            iso3="HND",
            nombre="Honduras",
            codigo_telefonico="+504",
            codigo_moneda="HNL",
            zona_horaria_predeterminada="America/Tegucigalpa",
        )
        cls.empresa = Empresa.objects.create(nombre="Analiza", pais=pais)
        tipo = TipoUbicacion.objects.get(codigo="SUCURSAL")
        cls.origen = Ubicacion.objects.create(
            nombre="Sucursal Centro",
            tipo_ubicacion=tipo,
            origen=OrigenUbicacion.REGISTRADA_USUARIO,
            pais=pais,
            direccion="Centro",
            latitud=Decimal("14.072300"),
            longitud=Decimal("-87.192100"),
        )
        cls.destino = Ubicacion.objects.create(
            nombre="Sucursal Norte",
            tipo_ubicacion=tipo,
            origen=OrigenUbicacion.REGISTRADA_USUARIO,
            pais=pais,
            direccion="Norte",
            latitud=Decimal("14.082300"),
            longitud=Decimal("-87.182100"),
        )
        cls.tipo_servicio = TipoServicio.objects.create(
            codigo="PRUEBA_RUTA", nombre="Prueba de ruta"
        )
        cls.administrador = Usuario.objetos.create(
            correo="admin.ruta@analiza.test",
            nombres="Administrador",
            apellidos="Ruta",
            empresa=cls.empresa,
            es_superusuario=True,
        )
        rol_motorista = Rol.objetos.get(codigo="REPARTIDOR_CORPORATIVO")
        cls.motoristas = []
        for indice in (1, 2):
            usuario = Usuario.objetos.create(
                correo=f"motorista.ruta{indice}@analiza.test",
                nombres=f"Motorista {indice}",
                apellidos="Ruta",
                empresa=cls.empresa,
            )
            RolUsuario.objetos.create(
                usuario=usuario,
                rol=rol_motorista,
                tipo_alcance=TipoAlcanceRol.EMPRESA,
                empresa=cls.empresa,
                asignado_por=cls.administrador,
            )
            cls.motoristas.append(
                Repartidor.objects.create(usuario=usuario, empresa=cls.empresa)
            )

    @property
    def motorista(self):
        return self.motoristas[0]

    def _crear_solicitud(
        self,
        numero,
        *,
        repartidor=None,
        minutos_atras=10,
        prioridad=PrioridadSolicitud.NORMAL,
        modalidad=ModalidadSolicitud.ENTRE_SUCURSALES,
        estado=EstadoSolicitud.ASIGNADA,
    ):
        repartidor = repartidor or self.motorista
        asignada_en = timezone.now() - timedelta(minutes=minutos_atras)
        especial = modalidad == ModalidadSolicitud.ESPECIAL
        solicitud = Solicitud.objects.create(
            cantidad_tubos=1,
            numero=numero,
            empresa=self.empresa,
            solicitada_por=self.administrador,
            repartidor_asignado=repartidor,
            prioridad=prioridad,
            modalidad=modalidad,
            tipo_servicio=self.tipo_servicio,
            origen=self.origen,
            destino=None if especial else self.destino,
            destino_especial="Archivo externo" if especial else None,
            estado=estado,
            asignada_en=asignada_en,
        )
        AsignacionSolicitud.objects.create(
            solicitud=solicitud,
            repartidor=repartidor,
            asignada_por=self.administrador,
            asignada_en=asignada_en,
        )
        return solicitud

    def _cliente(self, usuario):
        cliente = APIClient()
        cliente.force_authenticate(user=usuario)
        return cliente

    def test_sin_solicitudes_devuelve_lista_vacia_y_jornada_propia(self):
        jornada = JornadaRepartidor.objects.create(repartidor=self.motorista)
        respuesta = self._cliente(self.motorista.usuario).get(
            reverse("rutas:mi-ruta")
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data["jornada_id"], str(jornada.id))
        self.assertEqual(respuesta.data["paradas"], [])
        self.assertIsNone(respuesta.data["proxima_parada"])
        self.assertEqual(respuesta.data["orden_tipo"], "CERCANIA_GPS")
        self.assertFalse(respuesta.data["ruta_calculada"])
        self.assertIsNone(respuesta.data["ruta_id"])
        self.assertIsNone(respuesta.data["version_actual"])

    def test_versiones_inmutables_y_sin_duplicar_lecturas(self):
        solicitud = self._crear_solicitud("SOL-RUTA-VERSION")
        ruta = sincronizar_ruta(self.motorista, VersionRuta.Motivo.ASIGNACION)
        self.assertEqual(ruta.versiones.count(), 1)
        self.assertEqual(ruta.versiones.get().motivo, VersionRuta.Motivo.INICIAL)
        self.assertEqual(ruta.versiones.get().paradas.count(), 2)

        respuesta = self._cliente(self.motorista.usuario).get(reverse("rutas:mi-ruta"))
        self.assertEqual(respuesta.data["ruta_id"], str(ruta.id))
        self.assertEqual(respuesta.data["version_actual"], 1)
        sincronizar_ruta(self.motorista, VersionRuta.Motivo.CAMBIO_ESTADO)
        self.assertEqual(ruta.versiones.count(), 1)

        Solicitud.objects.filter(pk=solicitud.pk).update(estado=EstadoSolicitud.RECOLECTADA)
        sincronizar_ruta(self.motorista, VersionRuta.Motivo.CAMBIO_ESTADO)
        self.assertEqual(ruta.versiones.count(), 2)
        self.assertEqual(
            list(ruta.versiones.get(numero=1).paradas.values_list("tipo", flat=True)),
            ["RECOLECCION", "ENTREGA"],
        )
        self.assertEqual(
            list(ruta.versiones.get(numero=2).paradas.values_list("tipo", flat=True)),
            ["ENTREGA"],
        )
        self.destino.nombre = "Nombre actualizado"
        self.destino.save(update_fields=("nombre", "actualizado_en"))
        self.assertEqual(
            ParadaVersionRuta.objects.get(version__ruta=ruta, version__numero=1, orden=2).nombre_ubicacion,
            "Sucursal Norte",
        )

    def test_ruta_prejornada_se_vincula_y_cierra_sin_perder_historial(self):
        solicitud = self._crear_solicitud("SOL-RUTA-JORNADA")
        ruta = sincronizar_ruta(self.motorista, VersionRuta.Motivo.ASIGNACION)
        self.assertIsNone(ruta.jornada_id)
        jornada = JornadaRepartidor.objects.create(repartidor=self.motorista)
        sincronizar_ruta(
            self.motorista, VersionRuta.Motivo.INICIO_JORNADA, jornada=jornada
        )
        ruta.refresh_from_db()
        self.assertEqual(ruta.jornada_id, jornada.id)
        self.assertEqual(ruta.versiones.count(), 1)

        Solicitud.objects.filter(pk=solicitud.pk).update(estado=EstadoSolicitud.CANCELADA)
        AsignacionSolicitud.objects.filter(solicitud=solicitud).update(
            estado=EstadoAsignacionSolicitud.CANCELADA,
            finalizada_en=timezone.now(),
        )
        sincronizar_ruta(self.motorista, VersionRuta.Motivo.CANCELACION)
        self.assertEqual(ruta.versiones.get(numero=2).paradas.count(), 0)
        sincronizar_ruta(self.motorista, VersionRuta.Motivo.CIERRE_JORNADA, cerrar=True)
        ruta.refresh_from_db()
        self.assertEqual(ruta.estado, RutaRepartidor.Estado.FINALIZADA)
        self.assertEqual(ruta.versiones.count(), 2)

    def test_orden_estable_y_actualizacion_por_estado(self):
        primera = self._crear_solicitud("SOL-RUTA-1", minutos_atras=20)
        segunda = self._crear_solicitud("SOL-RUTA-2", minutos_atras=10)
        respuesta = self._cliente(self.motorista.usuario).get(
            reverse("rutas:mi-ruta")
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            [parada["tipo"] for parada in respuesta.data["paradas"]],
            ["RECOLECCION", "ENTREGA", "RECOLECCION", "ENTREGA"],
        )
        self.assertEqual(
            [parada["solicitud_id"] for parada in respuesta.data["paradas"]],
            [str(primera.id), str(primera.id), str(segunda.id), str(segunda.id)],
        )
        self.assertEqual(
            [parada["orden"] for parada in respuesta.data["paradas"]],
            [1, 2, 3, 4],
        )
        self.assertEqual(
            respuesta.data["proxima_parada"], respuesta.data["paradas"][0]
        )

        Solicitud.objects.filter(pk=primera.pk).update(
            estado=EstadoSolicitud.RECOLECTADA
        )
        Solicitud.objects.filter(pk=segunda.pk).update(
            estado=EstadoSolicitud.CANCELADA
        )
        actualizada = self._cliente(self.motorista.usuario).get(
            reverse("rutas:mi-ruta")
        )
        self.assertEqual(len(actualizada.data["paradas"]), 1)
        self.assertEqual(actualizada.data["paradas"][0]["tipo"], "ENTREGA")
        self.assertEqual(
            actualizada.data["paradas"][0]["solicitud_id"], str(primera.id)
        )

    def test_prioritario_recogido_va_directamente_al_destino(self):
        normal = self._crear_solicitud("SOL-RUTA-NORMAL", minutos_atras=20)
        prioritario = self._crear_solicitud(
            "SOL-RUTA-PRIORITARIO",
            minutos_atras=5,
            prioridad=PrioridadSolicitud.PRIORITARIA,
            estado=EstadoSolicitud.RECOLECTADA,
        )
        ruta = obtener_mi_ruta(self.motorista.usuario)

        self.assertEqual(ruta["paradas"][0]["solicitud_id"], prioritario.id)
        self.assertEqual(ruta["paradas"][0]["tipo"], "ENTREGA")
        self.assertEqual(
            [parada["solicitud_id"] for parada in ruta["paradas"][1:]],
            [normal.id, normal.id],
        )

    def test_especial_no_publica_destino_en_mapa(self):
        especial = self._crear_solicitud(
            "SOL-RUTA-ESPECIAL",
            modalidad=ModalidadSolicitud.ESPECIAL,
            estado=EstadoSolicitud.RECOLECTADA,
        )
        respuesta = self._cliente(self.motorista.usuario).get(
            reverse("rutas:mi-ruta")
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(len(respuesta.data["paradas"]), 1)
        parada = respuesta.data["paradas"][0]
        self.assertEqual(parada["solicitud_id"], str(especial.id))
        self.assertEqual(parada["tipo"], "ENVIO_ESPECIAL")
        self.assertIsNone(parada["ubicacion"])
        self.assertEqual(parada["destino_especial"], "Archivo externo")
        self.assertEqual(parada["presentacion_ruta"], "SOLO_KILOMETROS")

    def test_reasignacion_quita_paradas_del_motorista_anterior(self):
        solicitud = self._crear_solicitud("SOL-RUTA-REASIGNADA")
        asignacion = AsignacionSolicitud.objects.get(solicitud=solicitud)
        asignacion.estado = EstadoAsignacionSolicitud.REASIGNADA
        asignacion.finalizada_en = timezone.now()
        asignacion.save(update_fields=("estado", "finalizada_en"))
        nuevo_motorista = self.motoristas[1]
        AsignacionSolicitud.objects.create(
            solicitud=solicitud,
            repartidor=nuevo_motorista,
            asignada_por=self.administrador,
        )
        Solicitud.objects.filter(pk=solicitud.pk).update(
            repartidor_asignado=nuevo_motorista
        )

        ruta_anterior = self._cliente(self.motorista.usuario).get(
            reverse("rutas:mi-ruta")
        )
        ruta_nueva = self._cliente(nuevo_motorista.usuario).get(
            reverse("rutas:mi-ruta")
        )

        self.assertEqual(ruta_anterior.data["paradas"], [])
        self.assertEqual(len(ruta_nueva.data["paradas"]), 2)
        self.assertEqual(
            ruta_nueva.data["proxima_parada"]["solicitud_id"],
            str(solicitud.id),
        )

    def test_no_expone_servicios_ajenos_ni_permite_consulta_administrativa(self):
        self._crear_solicitud(
            "SOL-RUTA-AJENA", repartidor=self.motoristas[1]
        )
        propia = self._crear_solicitud("SOL-RUTA-PROPIA")
        respuesta = self._cliente(self.motorista.usuario).get(
            reverse("rutas:mi-ruta")
        )
        self.assertEqual(
            {parada["solicitud_id"] for parada in respuesta.data["paradas"]},
            {str(propia.id)},
        )
        sin_perfil = self._cliente(self.administrador).get(
            reverse("rutas:mi-ruta")
        )
        self.assertEqual(sin_perfil.status_code, 404)
        anonimo = APIClient().get(reverse("rutas:mi-ruta"))
        self.assertEqual(anonimo.status_code, 401)

    def test_motorista_sin_permiso_no_consulta_paradas(self):
        usuario = Usuario.objetos.create(
            correo="sin.permiso.ruta@analiza.test",
            nombres="Sin",
            apellidos="Permiso",
            empresa=self.empresa,
        )
        Repartidor.objects.create(usuario=usuario, empresa=self.empresa)
        respuesta = self._cliente(usuario).get(reverse("rutas:mi-ruta"))
        self.assertEqual(respuesta.status_code, 403)

    def test_historial_paginado_y_detalle_usan_snapshot_sin_escribir(self):
        solicitud = self._crear_solicitud("SOL-HISTORIAL-1")
        ruta = sincronizar_ruta(self.motorista, VersionRuta.Motivo.ASIGNACION)
        Solicitud.objects.filter(pk=solicitud.pk).update(
            estado=EstadoSolicitud.RECOLECTADA
        )
        sincronizar_ruta(self.motorista, VersionRuta.Motivo.CAMBIO_ESTADO)
        self.destino.nombre = "Nombre posterior"
        self.destino.save(update_fields=("nombre", "actualizado_en"))

        cliente = self._cliente(self.motorista.usuario)
        listado = cliente.get(reverse("rutas:listar-rutas"))
        self.assertEqual(listado.status_code, 200)
        self.assertEqual(listado.data["conteo"], 1)
        self.assertEqual(listado.data["resultados"][0]["id"], str(ruta.id))
        self.assertEqual(listado.data["resultados"][0]["cantidad_versiones"], 2)

        versiones = cliente.get(
            reverse("rutas:listar-versiones", args=[ruta.id]),
            {"tamano_pagina": 1},
        )
        self.assertEqual(versiones.status_code, 200)
        self.assertEqual(versiones.data["conteo"], 2)
        self.assertEqual(versiones.data["resultados"][0]["numero"], 2)
        self.assertIsNotNone(versiones.data["pagina_siguiente"])

        detalle = cliente.get(
            reverse("rutas:detalle-version", args=[ruta.id, 1])
        )
        self.assertEqual(detalle.status_code, 200)
        self.assertEqual(detalle.data["cantidad_paradas"], 2)
        self.assertEqual(detalle.data["paradas"][1]["ubicacion"]["nombre"], "Sucursal Norte")
        self.assertEqual(ruta.versiones.count(), 2)

        self.assertEqual(
            cliente.get(
                reverse("rutas:listar-rutas"), {"repartidor_id": "incorrecto"}
            ).status_code,
            400,
        )
        self.assertEqual(
            cliente.get(
                reverse("rutas:detalle-version", args=[ruta.id, 99])
            ).status_code,
            404,
        )

    def test_historial_admin_respeta_empresa_y_paradas_de_otras_empresas(self):
        solicitud = self._crear_solicitud("SOL-HISTORIAL-ALCANCE")
        ruta = sincronizar_ruta(self.motorista, VersionRuta.Motivo.ASIGNACION)
        gerente = Usuario.objetos.create(
            correo="gerente.rutas@analiza.test",
            nombres="Gerente", apellidos="Rutas", empresa=self.empresa,
        )
        otra_empresa = Empresa.objects.create(
            nombre="Otra empresa", pais=self.empresa.pais
        )
        gerente_ajeno = Usuario.objetos.create(
            correo="gerente.rutas@otra.test",
            nombres="Gerente", apellidos="Ajeno", empresa=otra_empresa,
        )
        rol = Rol.objetos.get(codigo="GERENTE_OPERACIONES")
        for usuario, empresa in (
            (gerente, self.empresa), (gerente_ajeno, otra_empresa)
        ):
            RolUsuario.objetos.create(
                usuario=usuario, rol=rol,
                tipo_alcance=TipoAlcanceRol.EMPRESA,
                empresa=empresa, asignado_por=self.administrador,
            )

        url = reverse("rutas:listar-versiones", args=[ruta.id])
        self.assertEqual(self._cliente(gerente).get(url).status_code, 200)
        self.assertEqual(self._cliente(gerente_ajeno).get(url).status_code, 404)
        self.assertEqual(
            self._cliente(gerente_ajeno).get(reverse("rutas:listar-rutas")).data["conteo"],
            0,
        )

        solicitud_ajena = Solicitud.objects.create(
            cantidad_tubos=1,
            numero="SOL-HISTORIAL-AJENA",
            empresa=otra_empresa,
            solicitada_por=gerente_ajeno,
            repartidor_asignado=self.motorista,
            prioridad=PrioridadSolicitud.NORMAL,
            modalidad=ModalidadSolicitud.ENTRE_SUCURSALES,
            tipo_servicio=self.tipo_servicio,
            origen=self.origen,
            destino=self.destino,
            estado=EstadoSolicitud.ASIGNADA,
            asignada_en=timezone.now(),
        )
        AsignacionSolicitud.objects.create(
            solicitud=solicitud_ajena,
            repartidor=self.motorista,
            asignada_por=self.administrador,
        )
        sincronizar_ruta(self.motorista, VersionRuta.Motivo.ASIGNACION)

        self.assertEqual(self._cliente(gerente).get(url).status_code, 404)
        self.assertEqual(
            self._cliente(gerente).get(reverse("rutas:listar-rutas")).data["conteo"],
            0,
        )
        self.assertEqual(self._cliente(self.motorista.usuario).get(url).status_code, 200)
        self.assertEqual(self._cliente(self.administrador).get(url).status_code, 200)
        self.assertEqual(solicitud.estado, EstadoSolicitud.ASIGNADA)

    def test_historial_exige_sesion_y_permiso_de_ruta(self):
        self._crear_solicitud("SOL-HISTORIAL-PERMISO")
        ruta = sincronizar_ruta(self.motorista, VersionRuta.Motivo.ASIGNACION)
        url = reverse("rutas:detalle-version", args=[ruta.id, 1])
        self.assertEqual(APIClient().get(url).status_code, 401)
        sin_permiso = Usuario.objetos.create(
            correo="sin.ruta@analiza.test",
            nombres="Sin", apellidos="Permiso", empresa=self.empresa,
        )
        self.assertEqual(self._cliente(sin_permiso).get(url).status_code, 403)
