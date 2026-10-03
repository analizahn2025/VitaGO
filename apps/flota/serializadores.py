from rest_framework import serializers

from apps.flota.models import Vehiculo
from apps.flota.opciones import EstadoVehiculo, TipoVehiculo


class SerializadorVehiculo(serializers.ModelSerializer):
    class Meta:
        model = Vehiculo
        fields = (
            "id",
            "empresa_id",
            "placa",
            "tipo",
            "marca",
            "modelo",
            "anio",
            "capacidad_carga_kg",
            "estado",
            "notas",
            "creado_en",
            "actualizado_en",
        )


class SerializadorCreacionVehiculo(serializers.Serializer):
    empresa_id = serializers.UUIDField(required=False, allow_null=True)
    placa = serializers.CharField(max_length=32)
    tipo = serializers.ChoiceField(choices=((TipoVehiculo.MOTOCICLETA, "Motocicleta"),))
    marca = serializers.CharField(
        max_length=80, required=False, allow_blank=True, allow_null=True
    )
    modelo = serializers.CharField(
        max_length=80, required=False, allow_blank=True, allow_null=True
    )
    anio = serializers.IntegerField(
        required=False, allow_null=True, min_value=1900, max_value=9999
    )
    estado = serializers.ChoiceField(
        choices=EstadoVehiculo.choices,
        default=EstadoVehiculo.ACTIVO,
    )
    notas = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )

    def validate_placa(self, valor):
        return valor.strip().upper()

    def validate(self, atributos):
        if "capacidad_carga_kg" in self.initial_data:
            raise serializers.ValidationError(
                {"capacidad_carga_kg": "Este campo es obsoleto y no editable."}
            )
        return atributos


class SerializadorConsultaVehiculos(serializers.Serializer):
    empresa_id = serializers.UUIDField(required=False)
    estado = serializers.ChoiceField(choices=EstadoVehiculo.choices, required=False)
    tipo = serializers.ChoiceField(choices=TipoVehiculo.choices, required=False)
