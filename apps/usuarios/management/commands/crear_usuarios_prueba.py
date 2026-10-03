"""Crea dos cuentas operativas desechables para Analiza Corporate local."""

import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.flota.models import Vehiculo
from apps.flota.opciones import TipoVehiculo
from apps.organizaciones.models import Empresa
from apps.organizaciones.opciones import EstadoOrganizacion
from apps.repartidores.models import Repartidor
from apps.usuarios.models import Rol, RolUsuario, Usuario
from apps.usuarios.opciones import EstadoUsuario, TipoAlcanceRol


CORREO_SOLICITANTE = "solicitante.prueba@analiza.test"
CORREO_MOTORISTA = "motorista.prueba@analiza.test"
PLACA_VEHICULO = "PRUEBA-ANALIZA-01"


class Command(BaseCommand):
    help = "Crea cuentas de solicitante y motorista solo en Analiza Corporate local."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirmar",
            action="store_true",
            help="Confirma la creación de datos de prueba en PostgreSQL.",
        )

    def handle(self, *args, **options):
        if not options["confirmar"]:
            raise CommandError("Agregue --confirmar para crear los datos de prueba.")
        if not (
            settings.DEBUG
            and settings.MODO_APLICACION == "CORPORATIVO"
            and settings.PROVEEDOR_AUTENTICACION == "LOCAL"
            and settings.DATABASES["default"]["NAME"] == "vitago_corporativo"
        ):
            raise CommandError(
                "Este comando solo puede ejecutarse en Analiza Corporate local "
                "con autenticación LOCAL y la base vitago_corporativo."
            )

        try:
            empresa = Empresa.objects.get(
                nombre="Analiza",
                estado=EstadoOrganizacion.ACTIVO,
            )
            rol_solicitante = Rol.objetos.get(
                codigo="SOLICITANTE_CORPORATIVO", activo=True
            )
            rol_motorista = Rol.objetos.get(
                codigo="REPARTIDOR_CORPORATIVO", activo=True
            )
        except (Empresa.DoesNotExist, Empresa.MultipleObjectsReturned, Rol.DoesNotExist) as error:
            raise CommandError(
                "Se requiere una única empresa Analiza activa y ambos roles activos."
            ) from error

        correos = (CORREO_SOLICITANTE, CORREO_MOTORISTA)
        if Usuario.objetos.filter(correo__in=correos).exists():
            raise CommandError(
                "Ya existe una cuenta de prueba con uno de esos correos; "
                "no se modificó ninguna contraseña ni usuario."
            )
        if Vehiculo.objects.filter(placa=PLACA_VEHICULO).exists():
            raise CommandError(
                "La placa de prueba ya existe; no se modificó ningún dato."
            )
        administrador = Usuario.objetos.filter(
            es_superusuario=True,
            estado=EstadoUsuario.ACTIVO,
        ).first()
        if administrador is None:
            raise CommandError(
                "Se requiere un superadministrador activo para auditar la asignación."
            )

        contrasena_solicitante = secrets.token_urlsafe(24)
        contrasena_motorista = secrets.token_urlsafe(24)
        with transaction.atomic():
            solicitante = Usuario.objetos.create_user(
                correo=CORREO_SOLICITANTE,
                password=contrasena_solicitante,
                nombres="Solicitante",
                apellidos="Prueba",
                empresa=empresa,
            )
            RolUsuario.objetos.create(
                usuario=solicitante,
                rol=rol_solicitante,
                tipo_alcance=TipoAlcanceRol.EMPRESA,
                empresa=empresa,
                asignado_por=administrador,
            )
            motorista = Usuario.objetos.create_user(
                correo=CORREO_MOTORISTA,
                password=contrasena_motorista,
                nombres="Motorista",
                apellidos="Prueba",
                empresa=empresa,
            )
            RolUsuario.objetos.create(
                usuario=motorista,
                rol=rol_motorista,
                tipo_alcance=TipoAlcanceRol.EMPRESA,
                empresa=empresa,
                asignado_por=administrador,
            )
            vehiculo = Vehiculo.objects.create(
                empresa=empresa,
                placa=PLACA_VEHICULO,
                tipo=TipoVehiculo.MOTOCICLETA,
                notas="Vehículo de prueba para desarrollo local; no usar en operación.",
            )
            Repartidor.objects.create(
                usuario=motorista,
                empresa=empresa,
                vehiculo=vehiculo,
            )

        self.stdout.write(self.style.SUCCESS("Cuentas de prueba creadas en Corporate local."))
        self.stdout.write(f"Solicitante: {CORREO_SOLICITANTE}")
        self.stdout.write(f"Contraseña solicitante: {contrasena_solicitante}")
        self.stdout.write(f"Motorista: {CORREO_MOTORISTA}")
        self.stdout.write(f"Contraseña motorista: {contrasena_motorista}")
        self.stdout.write(
            "Guarde estas contraseñas ahora: no se almacenan en texto claro "
            "ni se mostrarán al ejecutar nuevamente el comando."
        )
