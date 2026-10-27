"""Visibilidad y agrupación de solicitudes para administración."""

from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.geografia.models import Pais
from apps.organizaciones.models import Empresa, Sucursal
from apps.solicitudes.models import Solicitud, TipoServicio
from apps.solicitudes.opciones import PrioridadSolicitud
from apps.ubicaciones.models import TipoUbicacion, Ubicacion
from apps.ubicaciones.opciones import OrigenUbicacion
from apps.usuarios.models import Rol, RolUsuario, Usuario
from apps.usuarios.opciones import TipoAlcanceRol


@override_settings(
    MODO_APLICACION="CORPORATIVO",
    PROVEEDOR_AUTENTICACION="LOCAL",
)
class PruebasListadoAdministrativoSolicitudes(TestCase):
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
        cls.empresa_a = Empresa.objects.create(nombre="Analiza", pais=pais)
        cls.empresa_b = Empresa.objects.create(nombre="Otra empresa", pais=pais)
        tipo = TipoUbicacion.objects.get(codigo="SUCURSAL")
        cls.sucursales = []
        for indice, (empresa, nombre) in enumerate(
            (
                (cls.empresa_a, "Centro"),
                (cls.empresa_a, "Norte"),
                (cls.empresa_b, "Otra"),
            ),
            start=1,
        ):
            ubicacion = Ubicacion.objects.create(
                nombre=f"Ubicación {nombre}",
                tipo_ubicacion=tipo,
                origen=OrigenUbicacion.REGISTRADA_USUARIO,
                pais=pais,
                direccion=f"Dirección {nombre}",
                latitud=Decimal(f"14.0{indice}0000"),
                longitud=Decimal("-87.192100"),
            )
            cls.sucursales.append(
                Sucursal.objects.create(
                    empresa=empresa, nombre=nombre, ubicacion=ubicacion
                )
            )
        cls.tipo_servicio = TipoServicio.objects.create(
            codigo="PRUEBA_LISTADO_ADMIN", nombre="Prueba listado"
        )
        cls.superadministrador = cls._usuario(
            "superadmin@analiza.test", cls.empresa_a, es_superusuario=True
        )
        cls.administrador_a = cls._usuario(
            "administrador@analiza.test", cls.empresa_a
        )
        cls.solicitante_a = cls._usuario(
            "solicitante.a@analiza.test", cls.empresa_a
        )
        cls.solicitante_a2 = cls._usuario(
            "solicitante.b@analiza.test", cls.empresa_a
        )
        cls.solicitante_b = cls._usuario(
            "solicitante@otra.test", cls.empresa_b
        )
        cls._asignar_rol(
            cls.superadministrador, "SUPERADMINISTRADOR",
            TipoAlcanceRol.GLOBAL,
        )
        cls._asignar_rol(
            cls.administrador_a, "ADMINISTRADOR_CORPORATIVO",
            TipoAlcanceRol.EMPRESA, cls.empresa_a,
        )
        for usuario, empresa in (
            (cls.solicitante_a, cls.empresa_a),
            (cls.solicitante_a2, cls.empresa_a),
            (cls.solicitante_b, cls.empresa_b),
        ):
            cls._asignar_rol(
                usuario, "SOLICITANTE_CORPORATIVO",
                TipoAlcanceRol.EMPRESA, empresa,
            )
        cls.solicitudes = [
            cls._solicitud("SOL-ADMIN-1", cls.solicitante_a, cls.sucursales[0]),
            cls._solicitud("SOL-ADMIN-2", cls.solicitante_a, cls.sucursales[0]),
            cls._solicitud("SOL-ADMIN-3", cls.solicitante_a2, cls.sucursales[1]),
            cls._solicitud("SOL-ADMIN-4", cls.administrador_a, cls.sucursales[0]),
            cls._solicitud("SOL-ADMIN-5", cls.solicitante_b, cls.sucursales[2]),
        ]

    @classmethod
    def _usuario(cls, correo, empresa, *, es_superusuario=False):
        return Usuario.objetos.create(
            correo=correo,
            nombres=correo.split("@")[0],
            apellidos="Prueba",
            empresa=empresa,
            es_superusuario=es_superusuario,
        )

    @classmethod
    def _asignar_rol(cls, usuario, codigo, alcance, empresa=None):
        RolUsuario.objetos.create(
            usuario=usuario,
            rol=Rol.objetos.get(codigo=codigo),
            tipo_alcance=alcance,
            empresa=empresa,
            asignado_por=cls.superadministrador,
        )

    @classmethod
    def _solicitud(cls, numero, solicitante, sucursal):
        return Solicitud.objects.create(
            cantidad_tubos=1,
            numero=numero,
            empresa=sucursal.empresa,
            sucursal=sucursal,
            solicitada_por=solicitante,
            prioridad=PrioridadSolicitud.NORMAL,
            tipo_servicio=cls.tipo_servicio,
            origen=sucursal.ubicacion,
            destino=sucursal.ubicacion,
        )

    def _cliente(self, usuario):
        cliente = APIClient()
        cliente.force_authenticate(user=usuario)
        return cliente

    def test_superadministrador_ve_todas_y_datos_del_creador(self):
        cliente = self._cliente(self.superadministrador)
        respuesta = cliente.get(reverse("solicitudes:lista-creacion"))

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data["conteo"], 5)
        self.assertEqual(
            {fila["id"] for fila in respuesta.data["resultados"]},
            {str(solicitud.id) for solicitud in self.solicitudes},
        )
        fila = next(
            fila for fila in respuesta.data["resultados"]
            if fila["id"] == str(self.solicitudes[0].id)
        )
        self.assertEqual(
            fila["solicitante"]["nombres"], self.solicitante_a.nombres
        )
        self.assertEqual(fila["sucursal"]["nombre"], "Centro")
        self.assertNotIn("correo", fila["solicitante"])

        detalle = cliente.get(
            reverse(
                "solicitudes:detalle",
                kwargs={"solicitud_id": self.solicitudes[0].id},
            )
        )
        self.assertEqual(detalle.status_code, 200)
        self.assertEqual(
            detalle.data["solicitante"]["id"], str(self.solicitante_a.id)
        )

    def test_filtros_por_sucursal_y_solicitante_mantienen_alcance(self):
        ruta = reverse("solicitudes:lista-creacion")
        cliente = self._cliente(self.administrador_a)
        respuesta = cliente.get(ruta)
        self.assertEqual(respuesta.data["conteo"], 4)

        por_sucursal = cliente.get(
            ruta, {"sucursal_id": str(self.sucursales[0].id)}
        )
        self.assertEqual(por_sucursal.data["conteo"], 3)
        por_solicitante = cliente.get(
            ruta, {"solicitada_por_id": str(self.solicitante_a.id)}
        )
        self.assertEqual(por_solicitante.data["conteo"], 2)
        fuera_de_alcance = cliente.get(
            ruta, {"solicitada_por_id": str(self.solicitante_b.id)}
        )
        self.assertEqual(fuera_de_alcance.data["conteo"], 0)
        detalle_ajeno = cliente.get(
            reverse(
                "solicitudes:detalle",
                kwargs={"solicitud_id": self.solicitudes[4].id},
            )
        )
        self.assertEqual(detalle_ajeno.status_code, 404)

        cliente = self._cliente(self.solicitante_a)
        intento_ajeno = cliente.get(
            ruta, {"solicitada_por_id": str(self.solicitante_a2.id)}
        )
        self.assertEqual(intento_ajeno.data["conteo"], 0)
        self.assertEqual(cliente.get(ruta).data["conteo"], 2)

    def test_agrupaciones_paginadas_respetan_alcance_administrativo(self):
        ruta = reverse("solicitudes:agrupaciones")
        cliente = self._cliente(self.administrador_a)
        por_sucursal = cliente.get(ruta, {"por": "sucursal"})
        self.assertEqual(por_sucursal.status_code, 200)
        self.assertEqual(por_sucursal.data["conteo"], 2)
        self.assertEqual(
            {grupo["sucursal_id"]: grupo["total"]
             for grupo in por_sucursal.data["resultados"]},
            {self.sucursales[0].id: 3, self.sucursales[1].id: 1},
        )
        por_solicitante = cliente.get(
            ruta, {"por": "solicitante", "tamano_pagina": 1}
        )
        self.assertEqual(por_solicitante.status_code, 200)
        self.assertEqual(por_solicitante.data["conteo"], 3)
        self.assertEqual(len(por_solicitante.data["resultados"]), 1)
        self.assertIsNotNone(por_solicitante.data["pagina_siguiente"])
        todos_los_solicitantes = cliente.get(ruta, {"por": "solicitante"})
        self.assertEqual(
            {grupo["solicitada_por_id"]: grupo["total"]
             for grupo in todos_los_solicitantes.data["resultados"]},
            {
                self.solicitante_a.id: 2,
                self.solicitante_a2.id: 1,
                self.administrador_a.id: 1,
            },
        )

        cliente = self._cliente(self.superadministrador)
        todas = cliente.get(ruta, {"por": "sucursal"})
        self.assertEqual(todas.data["conteo"], 3)
        solo_analiza = cliente.get(
            ruta, {"por": "sucursal", "empresa_id": str(self.empresa_a.id)}
        )
        self.assertEqual(solo_analiza.data["conteo"], 2)

    def test_agrupaciones_rechazan_solicitante_y_parametro_invalido(self):
        ruta = reverse("solicitudes:agrupaciones")
        solicitante = self._cliente(self.solicitante_a)
        self.assertEqual(
            solicitante.get(ruta, {"por": "sucursal"}).status_code, 403
        )
        administrador = self._cliente(self.administrador_a)
        self.assertEqual(
            administrador.get(ruta, {"por": "otro"}).status_code, 400
        )

    def test_grupo_sin_sucursal_tiene_filtro_propio(self):
        Solicitud.objects.create(
            cantidad_tubos=1,
            numero="SOL-ADMIN-SIN-SUCURSAL",
            empresa=self.empresa_a,
            solicitada_por=self.solicitante_a,
            prioridad=PrioridadSolicitud.NORMAL,
            tipo_servicio=self.tipo_servicio,
            origen=self.sucursales[0].ubicacion,
            destino=self.sucursales[1].ubicacion,
        )
        cliente = self._cliente(self.administrador_a)
        grupos = cliente.get(
            reverse("solicitudes:agrupaciones"), {"por": "sucursal"}
        )
        sin_sucursal = next(
            grupo for grupo in grupos.data["resultados"]
            if grupo["sucursal_id"] is None
        )
        self.assertEqual(sin_sucursal["total"], 1)
        listado = cliente.get(
            reverse("solicitudes:lista-creacion"),
            {"sin_sucursal": "true"},
        )
        self.assertEqual(listado.data["conteo"], 1)
        invalido = cliente.get(
            reverse("solicitudes:lista-creacion"),
            {"sucursal_id": str(self.sucursales[0].id), "sin_sucursal": "true"},
        )
        self.assertEqual(invalido.status_code, 400)
