"""Serializadores de perfiles y administración de usuarios."""

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as ValidacionDjango
from rest_framework import serializers

from apps.usuarios.models import Rol, RolUsuario, Usuario
from apps.usuarios.opciones import EstadoUsuario, TipoAlcanceRol


class SerializadorResumenOrganizacion(serializers.Serializer):
    id = serializers.UUIDField()
    nombre = serializers.CharField()


class SerializadorUsuarioPerfil(serializers.Serializer):
    id = serializers.UUIDField()
    correo = serializers.EmailField()
    nombres = serializers.CharField()
    apellidos = serializers.CharField()
    telefono = serializers.CharField(allow_blank=True, allow_null=True)
    estado = serializers.CharField()


class SerializadorRolPerfil(serializers.Serializer):
    codigo = serializers.CharField()
    nombre = serializers.CharField()
    tipo_alcance = serializers.CharField()
    empresa_id = serializers.UUIDField(allow_null=True)
    sucursal_id = serializers.UUIDField(allow_null=True)


class SerializadorPerfilUsuario(serializers.Serializer):
    usuario = SerializadorUsuarioPerfil()
    empresa = SerializadorResumenOrganizacion(allow_null=True)
    sucursal = SerializadorResumenOrganizacion(allow_null=True)
    roles = SerializadorRolPerfil(many=True)
    permisos = serializers.ListField(child=serializers.CharField())


class SerializadorUsuarioAdministrado(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()

    class Meta:
        model = Usuario
        fields = (
            "id",
            "correo",
            "nombres",
            "apellidos",
            "telefono",
            "empresa_id",
            "sucursal_id",
            "estado",
            "roles",
            "creado_en",
        )

    def get_roles(self, usuario):
        asignaciones = [
            asignacion
            for asignacion in usuario.asignaciones_roles.all()
            if asignacion.activo and asignacion.rol.activo
        ]
        return [
            {
                "codigo": asignacion.rol.codigo,
                "nombre": asignacion.rol.nombre,
                "tipo_alcance": asignacion.tipo_alcance,
                "empresa_id": asignacion.empresa_id,
                "sucursal_id": asignacion.sucursal_id,
            }
            for asignacion in asignaciones
        ]


class SerializadorCreacionUsuario(serializers.Serializer):
    correo = serializers.EmailField(max_length=254)
    nombres = serializers.CharField(max_length=150)
    apellidos = serializers.CharField(max_length=150)
    telefono = serializers.CharField(
        max_length=32,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    contrasena_temporal = serializers.CharField(
        max_length=128,
        required=False,
        write_only=True,
        trim_whitespace=False,
    )
    identificador_autenticacion_externa = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=False,
    )
    rol_codigo = serializers.CharField(max_length=80)
    tipo_alcance = serializers.ChoiceField(choices=TipoAlcanceRol.choices)
    empresa_id = serializers.UUIDField(required=False, allow_null=True)
    sucursal_id = serializers.UUIDField(required=False, allow_null=True)

    def validate_correo(self, valor):
        return Usuario.objetos.normalize_email(valor).casefold()

    def validate_rol_codigo(self, valor):
        return valor.strip().upper()

    def validate(self, atributos):
        contrasena = atributos.get("contrasena_temporal")
        identificador_externo = atributos.get(
            "identificador_autenticacion_externa"
        )
        if settings.PROVEEDOR_AUTENTICACION == "LOCAL":
            if not contrasena:
                raise serializers.ValidationError(
                    {
                        "contrasena_temporal": (
                            "Es obligatoria con la autenticación local."
                        )
                    }
                )
            if identificador_externo:
                raise serializers.ValidationError(
                    {
                        "identificador_autenticacion_externa": (
                            "No debe enviarse con la autenticación local."
                        )
                    }
                )
            usuario_provisional = Usuario(
                correo=atributos["correo"],
                nombres=atributos["nombres"],
                apellidos=atributos["apellidos"],
            )
            try:
                validate_password(contrasena, user=usuario_provisional)
            except ValidacionDjango as error:
                raise serializers.ValidationError(
                    {"contrasena_temporal": list(error.messages)}
                ) from error
        else:
            if contrasena:
                raise serializers.ValidationError(
                    {
                        "contrasena_temporal": (
                            "No se admite con la autenticación corporativa."
                        )
                    }
                )
            if not identificador_externo:
                raise serializers.ValidationError(
                    {
                        "identificador_autenticacion_externa": (
                            "Es obligatorio con la autenticación corporativa."
                        )
                    }
                )
        return atributos


class SerializadorConsultaRolesAsignables(serializers.Serializer):
    tipo_alcance = serializers.ChoiceField(choices=TipoAlcanceRol.choices)
    empresa_id = serializers.UUIDField(required=False, allow_null=True)
    sucursal_id = serializers.UUIDField(required=False, allow_null=True)


class SerializadorRolAsignable(serializers.ModelSerializer):
    class Meta:
        model = Rol
        fields = (
            "codigo",
            "nombre",
            "descripcion",
            "permite_alcance_global",
            "permite_alcance_empresa",
            "permite_alcance_sucursal",
        )


class SerializadorAsignacionRol(serializers.Serializer):
    rol_codigo = serializers.CharField(max_length=80)
    tipo_alcance = serializers.ChoiceField(choices=TipoAlcanceRol.choices)
    empresa_id = serializers.UUIDField(required=False, allow_null=True)
    sucursal_id = serializers.UUIDField(required=False, allow_null=True)

    def validate_rol_codigo(self, valor):
        return valor.strip().upper()


class SerializadorAsignacionRolUsuario(serializers.ModelSerializer):
    rol = SerializadorRolAsignable(read_only=True)

    class Meta:
        model = RolUsuario
        fields = (
            "id",
            "rol",
            "tipo_alcance",
            "empresa_id",
            "sucursal_id",
            "activo",
            "asignado_por_id",
            "asignado_en",
            "revocado_por_id",
            "revocado_en",
        )


class SerializadorActualizacionUsuario(serializers.Serializer):
    nombres = serializers.CharField(max_length=150, required=False)
    apellidos = serializers.CharField(max_length=150, required=False)
    telefono = serializers.CharField(
        max_length=32,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    estado = serializers.ChoiceField(
        choices=EstadoUsuario.choices,
        required=False,
    )

    def validate(self, atributos):
        if not atributos:
            raise serializers.ValidationError(
                "Debe enviar al menos un campo para actualizar."
            )
        return atributos


class SerializadorRestablecimientoContrasena(serializers.Serializer):
    contrasena_temporal = serializers.CharField(
        max_length=128,
        write_only=True,
        trim_whitespace=False,
    )

    def validate_contrasena_temporal(self, valor):
        usuario = self.context["usuario_objetivo"]
        try:
            validate_password(valor, user=usuario)
        except ValidacionDjango as error:
            raise serializers.ValidationError(list(error.messages)) from error
        return valor
