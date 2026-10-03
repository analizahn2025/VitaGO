"""Serializadores de lectura para empresas y sucursales."""

from rest_framework import serializers

from apps.organizaciones.models import Empresa, Sucursal


class SerializadorPaisOrganizacion(serializers.Serializer):
    id = serializers.UUIDField()
    iso2 = serializers.CharField()
    nombre = serializers.CharField()
    codigo_moneda = serializers.CharField()
    zona_horaria_predeterminada = serializers.CharField()


class SerializadorEmpresa(serializers.ModelSerializer):
    pais = SerializadorPaisOrganizacion(read_only=True)

    class Meta:
        model = Empresa
        fields = (
            "id",
            "nombre",
            "razon_social",
            "identificacion_fiscal",
            "telefono",
            "correo",
            "pais",
            "estado",
        )


class SerializadorTipoUbicacionResumen(serializers.Serializer):
    id = serializers.UUIDField()
    codigo = serializers.CharField()
    nombre = serializers.CharField()


class SerializadorUbicacionResumen(serializers.Serializer):
    id = serializers.UUIDField()
    nombre = serializers.CharField()
    tipo_ubicacion = SerializadorTipoUbicacionResumen()
    direccion = serializers.CharField()
    latitud = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitud = serializers.DecimalField(max_digits=9, decimal_places=6)
    estado = serializers.CharField()


class SerializadorSucursal(serializers.ModelSerializer):
    ubicacion = SerializadorUbicacionResumen(read_only=True)

    class Meta:
        model = Sucursal
        fields = (
            "id",
            "empresa_id",
            "nombre",
            "codigo",
            "telefono",
            "correo",
            "estado",
            "ubicacion",
        )


class SerializadorCreacionSucursal(serializers.Serializer):
    nombre = serializers.CharField(max_length=200)
    codigo = serializers.CharField(
        max_length=64,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    ubicacion_id = serializers.UUIDField()
    telefono = serializers.CharField(
        max_length=32,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    correo = serializers.EmailField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )
