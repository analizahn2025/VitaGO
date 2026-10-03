"""Serializadores HTTP del dominio de ubicaciones."""

from decimal import Decimal

from rest_framework import serializers

from apps.ubicaciones.models import TipoUbicacion, Ubicacion, UbicacionEmpresa
from apps.ubicaciones.opciones import (
    EstadoUbicacionEmpresa,
    OrigenUbicacion,
)


class SerializadorTipoUbicacion(serializers.ModelSerializer):
    class Meta:
        model = TipoUbicacion
        fields = ("id", "codigo", "nombre")


class SerializadorPaisUbicacion(serializers.Serializer):
    id = serializers.UUIDField()
    iso2 = serializers.CharField()
    nombre = serializers.CharField()


class SerializadorUbicacionAdministrada(serializers.ModelSerializer):
    tipo_ubicacion = SerializadorTipoUbicacion(read_only=True)
    pais = SerializadorPaisUbicacion(read_only=True)
    departamento = serializers.CharField(
        source="nivel_administrativo_1",
        read_only=True,
        allow_null=True,
    )
    municipio = serializers.CharField(
        source="nivel_administrativo_2",
        read_only=True,
        allow_null=True,
    )
    ciudad = serializers.CharField(
        source="localidad",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = Ubicacion
        fields = (
            "id",
            "nombre",
            "tipo_ubicacion",
            "origen",
            "identificador_lugar_google",
            "pais",
            "departamento",
            "municipio",
            "ciudad",
            "colonia",
            "direccion",
            "latitud",
            "longitud",
            "telefono",
            "nombre_contacto",
            "horario_atencion",
            "instrucciones",
            "verificada",
            "estado",
            "creado_en",
            "actualizado_en",
        )


class SerializadorRelacionUbicacionEmpresa(serializers.ModelSerializer):
    empresa_id = serializers.UUIDField(read_only=True)
    ubicacion = SerializadorUbicacionAdministrada(read_only=True)

    class Meta:
        model = UbicacionEmpresa
        fields = (
            "id",
            "empresa_id",
            "permite_origen",
            "permite_destino",
            "estado",
            "ubicacion",
        )


class SerializadorCreacionUbicacion(serializers.Serializer):
    empresa_id = serializers.UUIDField(write_only=True)
    nombre = serializers.CharField(max_length=200)
    tipo_ubicacion_id = serializers.UUIDField(write_only=True)
    origen = serializers.ChoiceField(choices=OrigenUbicacion.choices)
    identificador_lugar_google = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    pais_id = serializers.UUIDField(write_only=True)
    departamento = serializers.CharField(
        source="nivel_administrativo_1",
        max_length=150,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    municipio = serializers.CharField(
        source="nivel_administrativo_2",
        max_length=150,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    ciudad = serializers.CharField(
        source="localidad",
        max_length=150,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    colonia = serializers.CharField(
        max_length=150,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    direccion = serializers.CharField()
    latitud = serializers.DecimalField(
        max_digits=9,
        decimal_places=6,
        min_value=Decimal("-90"),
        max_value=Decimal("90"),
    )
    longitud = serializers.DecimalField(
        max_digits=9,
        decimal_places=6,
        min_value=Decimal("-180"),
        max_value=Decimal("180"),
    )
    telefono = serializers.CharField(
        max_length=32,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    nombre_contacto = serializers.CharField(
        max_length=200,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    horario_atencion = serializers.JSONField(required=False, allow_null=True)
    instrucciones = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    permite_origen = serializers.BooleanField()
    permite_destino = serializers.BooleanField()

    def validate(self, atributos):
        origen = atributos["origen"]
        identificador_google = atributos.get("identificador_lugar_google")
        if origen == OrigenUbicacion.GOOGLE and not identificador_google:
            raise serializers.ValidationError(
                {
                    "identificador_lugar_google": (
                        "Es obligatorio para ubicaciones provenientes de Google."
                    )
                }
            )
        if (
            origen == OrigenUbicacion.REGISTRADA_USUARIO
            and identificador_google
        ):
            raise serializers.ValidationError(
                {
                    "identificador_lugar_google": (
                        "No debe enviarse para una ubicación registrada manualmente."
                    )
                }
            )
        if not atributos["permite_origen"] and not atributos["permite_destino"]:
            raise serializers.ValidationError(
                "La ubicación debe permitir origen, destino o ambos."
            )
        return atributos


class SerializadorFiltroUbicaciones(serializers.Serializer):
    empresa_id = serializers.UUIDField(required=True)


class SerializadorActualizacionAutorizacion(serializers.Serializer):
    permite_origen = serializers.BooleanField(required=False)
    permite_destino = serializers.BooleanField(required=False)
    estado = serializers.ChoiceField(
        choices=EstadoUbicacionEmpresa.choices,
        required=False,
    )

    def validate(self, atributos):
        if not atributos:
            raise serializers.ValidationError(
                "Debe enviar al menos un campo para actualizar."
            )
        return atributos
