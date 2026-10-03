"""Prepara un escenario ficticio y repetible para Analiza Corporate local."""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError as ErrorValidacionDjango
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.http import Http404
from rest_framework.exceptions import (
    PermissionDenied,
    ValidationError as ErrorValidacionAPI,
)

from apps.organizaciones.models import Empresa, Sucursal
from apps.organizaciones.opciones import EstadoOrganizacion
from apps.repartidores.models import Repartidor
from apps.solicitudes.models import Solicitud, TipoServicio
from apps.solicitudes.opciones import ModalidadSolicitud, PrioridadSolicitud
from apps.solicitudes.servicios import (
    crear_solicitud,
)
from apps.ubicaciones.models import TipoUbicacion, Ubicacion, UbicacionEmpresa
from apps.ubicaciones.opciones import (
    EstadoUbicacion,
    EstadoUbicacionEmpresa,
    OrigenUbicacion,
)
from apps.usuarios.models import Usuario
from apps.usuarios.opciones import EstadoUsuario


MARCA_ENTRE_SUCURSALES = "VITAGO_PRUEBA_CORPORATIVA_ENTRE_SUCURSALES"
MARCA_EMPRESA_TRANSPORTE = "VITAGO_PRUEBA_CORPORATIVA_EMPRESA_TRANSPORTE"

UBICACIONES_PRUEBA = (
    {
        "nombre": "Prueba - Sucursal Centro",
        "tipo": "SUCURSAL",
        "colonia": "Centro",
        "latitud": "14.091000",
        "longitud": "-87.206000",
        "permite_origen": True,
        "permite_destino": True,
    },
    {
        "nombre": "Prueba - Sucursal Norte",
        "tipo": "SUCURSAL",
        "colonia": "Norte",
        "latitud": "14.105000",
        "longitud": "-87.195000",
        "permite_origen": True,
        "permite_destino": True,
    },
    {
        "nombre": "Prueba - Empresa de transporte",
        "tipo": "EMPRESA_TRANSPORTE",
        "colonia": "Centro",
        "latitud": "14.083000",
        "longitud": "-87.210000",
        "permite_origen": False,
        "permite_destino": True,
    },
)


class Command(BaseCommand):
    help = "Crea sucursales, ubicaciones y solicitudes ficticias en Corporate local."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirmar",
            action="store_true",
            help="Confirma la escritura de datos de prueba en vitago_corporativo.",
        )

    def _validar_entorno(self):
        if not (
            settings.DEBUG
            and settings.ENTORNO == "LOCAL"
            and settings.MODO_APLICACION == "CORPORATIVO"
            and settings.PROVEEDOR_AUTENTICACION == "LOCAL"
            and settings.DATABASES["default"]["NAME"] == "vitago_corporativo"
        ):
            raise CommandError(
                "Este comando solo admite Corporate LOCAL con autenticación "
                "LOCAL y la base vitago_corporativo."
            )

    def _obtener_prerrequisitos(self):
        try:
            empresa = Empresa.objects.select_related("pais").get(
                nombre="Analiza", estado=EstadoOrganizacion.ACTIVO
            )
            solicitante = Usuario.objetos.get(
                correo="solicitante.prueba@analiza.test",
                empresa=empresa,
                estado=EstadoUsuario.ACTIVO,
            )
            motorista = Usuario.objetos.get(
                correo="motorista.prueba@analiza.test",
                empresa=empresa,
                estado=EstadoUsuario.ACTIVO,
            )
            repartidor = Repartidor.objects.get(
                usuario=motorista, empresa=empresa, activo=True
            )
            administrador = Usuario.objetos.filter(
                es_superusuario=True, estado=EstadoUsuario.ACTIVO
            ).first()
            tipo_documento = TipoServicio.objects.get(
                codigo="DOCUMENTO", activo=True
            )
            tipo_paquete = TipoServicio.objects.get(
                codigo="PAQUETE", activo=True
            )
            tipos_ubicacion = {
                codigo: TipoUbicacion.objects.get(codigo=codigo, activo=True)
                for codigo in ("SUCURSAL", "EMPRESA_TRANSPORTE")
            }
        except (
            Empresa.DoesNotExist,
            Empresa.MultipleObjectsReturned,
            Usuario.DoesNotExist,
            Repartidor.DoesNotExist,
            TipoServicio.DoesNotExist,
            TipoUbicacion.DoesNotExist,
        ) as error:
            raise CommandError(
                "Faltan Analiza, las cuentas de prueba, el motorista o "
                "los catálogos activos requeridos."
            ) from error
        if administrador is None:
            raise CommandError("Se requiere un superadministrador activo.")
        return (
            empresa,
            solicitante,
            repartidor,
            administrador,
            tipo_documento,
            tipo_paquete,
            tipos_ubicacion,
        )

    def _obtener_ubicacion(self, empresa, administrador, tipos, datos):
        ubicacion, _ = Ubicacion.objects.get_or_create(
            nombre=datos["nombre"],
            pais=empresa.pais,
            defaults={
                "tipo_ubicacion": tipos[datos["tipo"]],
                "origen": OrigenUbicacion.REGISTRADA_USUARIO,
                "nivel_administrativo_1": "Francisco Morazán",
                "nivel_administrativo_2": "Distrito Central",
                "localidad": "Tegucigalpa",
                "colonia": datos["colonia"],
                "direccion": "Dirección ficticia para pruebas; no usar en operación.",
                "latitud": Decimal(datos["latitud"]),
                "longitud": Decimal(datos["longitud"]),
                "verificada": False,
                "estado": EstadoUbicacion.ACTIVO,
                "creada_por": administrador.id,
            },
        )
        if (
            ubicacion.tipo_ubicacion_id != tipos[datos["tipo"]].id
            or ubicacion.estado != EstadoUbicacion.ACTIVO
            or (ubicacion.localidad or "").casefold() != "tegucigalpa"
        ):
            raise CommandError(
                f"La ubicación {datos['nombre']} ya existe con datos incompatibles."
            )
        relacion, _ = UbicacionEmpresa.objects.get_or_create(
            empresa=empresa,
            ubicacion=ubicacion,
            defaults={
                "permite_origen": datos["permite_origen"],
                "permite_destino": datos["permite_destino"],
                "estado": EstadoUbicacionEmpresa.APROBADO,
            },
        )
        if (
            relacion.estado != EstadoUbicacionEmpresa.APROBADO
            or relacion.permite_origen != datos["permite_origen"]
            or relacion.permite_destino != datos["permite_destino"]
        ):
            raise CommandError(
                f"La autorización de {datos['nombre']} ya existe con datos incompatibles."
            )
        return ubicacion

    def _obtener_sucursal(self, empresa, nombre, codigo, ubicacion):
        sucursal, _ = Sucursal.objects.get_or_create(
            empresa=empresa,
            codigo=codigo,
            defaults={
                "nombre": nombre,
                "ubicacion": ubicacion,
                "estado": EstadoOrganizacion.ACTIVO,
            },
        )
        if (
            sucursal.nombre != nombre
            or sucursal.ubicacion_id != ubicacion.id
            or sucursal.estado != EstadoOrganizacion.ACTIVO
        ):
            raise CommandError(
                f"La sucursal de prueba {codigo} ya existe con datos incompatibles."
            )
        return sucursal

    def _obtener_solicitud(
        self,
        empresa,
        solicitante,
        sucursal,
        destino,
        tipo_servicio,
        modalidad,
        marca,
    ):
        existentes = list(
            Solicitud.objects.filter(
                empresa=empresa, solicitada_por=solicitante, notas=marca
            )[:2]
        )
        if len(existentes) > 1:
            raise CommandError(f"Hay solicitudes de prueba duplicadas: {marca}.")
        if existentes:
            solicitud = existentes[0]
            if (
                solicitud.modalidad != modalidad
                or solicitud.origen_id != sucursal.ubicacion_id
                or solicitud.destino_id != destino.id
            ):
                raise CommandError(
                    f"La solicitud de prueba {marca} tiene datos incompatibles."
                )
            return solicitud, False
        solicitud = crear_solicitud(
            solicitante,
            {
                "empresa_id": empresa.id,
                "sucursal_id": sucursal.id,
                "prioridad": PrioridadSolicitud.NORMAL,
                "modalidad": modalidad,
                "tipo_servicio_id": tipo_servicio.id,
                "origen_id": sucursal.ubicacion_id,
                "destino_id": destino.id,
                "notas": marca,
                "articulos": [
                    {
                        "tipo_articulo": "Artículo de prueba",
                        "descripcion": "Contenido ficticio sin valor operativo.",
                        "cantidad": Decimal("1"),
                    }
                ],
            },
        )
        return solicitud, True

    def handle(self, *args, **options):
        if not options["confirmar"]:
            raise CommandError("Agregue --confirmar para crear datos de prueba.")
        self._validar_entorno()
        try:
            with transaction.atomic():
                (
                    empresa,
                    solicitante,
                    _repartidor,
                    administrador,
                    tipo_documento,
                    tipo_paquete,
                    tipos_ubicacion,
                ) = self._obtener_prerrequisitos()
                ubicaciones = {
                    datos["nombre"]: self._obtener_ubicacion(
                        empresa, administrador, tipos_ubicacion, datos
                    )
                    for datos in UBICACIONES_PRUEBA
                }
                sucursal_centro = self._obtener_sucursal(
                    empresa,
                    "Prueba - Centro",
                    "PRUEBA-CENTRO",
                    ubicaciones["Prueba - Sucursal Centro"],
                )
                sucursal_norte = self._obtener_sucursal(
                    empresa,
                    "Prueba - Norte",
                    "PRUEBA-NORTE",
                    ubicaciones["Prueba - Sucursal Norte"],
                )
                entre_sucursales, _ = self._obtener_solicitud(
                    empresa,
                    solicitante,
                    sucursal_centro,
                    sucursal_norte.ubicacion,
                    tipo_documento,
                    ModalidadSolicitud.ENTRE_SUCURSALES,
                    MARCA_ENTRE_SUCURSALES,
                )
                empresa_transporte, _ = self._obtener_solicitud(
                    empresa,
                    solicitante,
                    sucursal_centro,
                    ubicaciones["Prueba - Empresa de transporte"],
                    tipo_paquete,
                    ModalidadSolicitud.EMPRESA_TRANSPORTE,
                    MARCA_EMPRESA_TRANSPORTE,
                )
        except (
            Http404,
            PermissionDenied,
            ErrorValidacionAPI,
            ErrorValidacionDjango,
        ) as error:
            raise CommandError(f"No se pudo preparar el escenario: {error}") from error

        self.stdout.write(self.style.SUCCESS("Escenario de prueba Corporate listo."))
        self.stdout.write(
            f"Sucursales: {sucursal_centro.nombre} ({sucursal_centro.id}), "
            f"{sucursal_norte.nombre} ({sucursal_norte.id})"
        )
        self.stdout.write(
            f"Entre sucursales: {entre_sucursales.numero} ({entre_sucursales.id})"
        )
        self.stdout.write(
            f"Empresa de transporte: {empresa_transporte.numero} "
            f"({empresa_transporte.id})"
        )
