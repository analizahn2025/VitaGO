from decimal import Decimal

from rest_framework import serializers

from apps.seguimiento.models import RegistroUbicacion


class SerializadorRegistroUbicacionEntrada(serializers.Serializer):
    id_cliente = serializers.UUIDField()
    latitud = serializers.DecimalField(
        max_digits=9,
        decimal_places=6,
        min_value=-90,
        max_value=90,
    )
    longitud = serializers.DecimalField(
        max_digits=9,
        decimal_places=6,
        min_value=-180,
        max_value=180,
    )
    precision_metros = serializers.DecimalField(
        max_digits=8,
        decimal_places=2,
        min_value=0,
        required=False,
        allow_null=True,
    )
    velocidad_metros_segundo = serializers.DecimalField(
        max_digits=8,
        decimal_places=3,
        min_value=0,
        required=False,
        allow_null=True,
    )
    rumbo_grados = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        min_value=Decimal("0"),
        max_value=Decimal("359.99"),
        required=False,
        allow_null=True,
    )
    registrada_en = serializers.DateTimeField()


class SerializadorLoteRegistrosUbicacion(serializers.Serializer):
    jornada_id = serializers.UUIDField()
    registros = SerializadorRegistroUbicacionEntrada(many=True)

    def validate_registros(self, registros):
        if not registros:
            raise serializers.ValidationError(
                "Debe enviar al menos un registro de ubicación."
            )
        if len(registros) > 200:
            raise serializers.ValidationError(
                "No puede enviar más de 200 registros por solicitud."
            )
        identificadores = [registro["id_cliente"] for registro in registros]
        if len(identificadores) != len(set(identificadores)):
            raise serializers.ValidationError(
                "Cada id_cliente debe ser único dentro del lote."
            )
        return registros


class SerializadorRegistroUbicacion(serializers.ModelSerializer):
    class Meta:
        model = RegistroUbicacion
        fields = (
            "id", "id_cliente", "jornada_id", "repartidor_id", "latitud",
            "longitud", "precision_metros", "velocidad_metros_segundo",
            "rumbo_grados", "registrada_en", "es_operativo", "creado_en",
            "movimiento_envio_especial_id",
        )


class SerializadorSeguimientoSolicitud(serializers.Serializer):
    solicitud_id = serializers.UUIDField()
    estado = serializers.CharField()
    seguimiento_disponible = serializers.BooleanField()
    ubicacion = SerializadorRegistroUbicacion(allow_null=True)
