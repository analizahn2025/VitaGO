from rest_framework import serializers

from apps.flota.serializadores import SerializadorVehiculo
from apps.repartidores.capacidad import (
    LIMITE_SOLICITUDES,
    calcular_capacidad,
    contar_solicitudes_activas,
    puede_recibir_solicitudes,
)
from apps.repartidores.models import Repartidor
from apps.repartidores.opciones import (
    CapacidadRepartidor,
    EstadoOperativoRepartidor,
)
from apps.usuarios.serializadores import SerializadorUsuarioPerfil


class SerializadorRepartidor(serializers.ModelSerializer):
    usuario = SerializadorUsuarioPerfil(read_only=True)
    vehiculo = SerializadorVehiculo(read_only=True)
    capacidad = serializers.SerializerMethodField()
    solicitudes_activas = serializers.SerializerMethodField()
    limite_solicitudes = serializers.SerializerMethodField()
    puede_recibir_solicitudes = serializers.SerializerMethodField()

    def _cantidad(self, repartidor):
        cantidad = getattr(repartidor, "solicitudes_activas_calculadas", None)
        return cantidad if cantidad is not None else contar_solicitudes_activas(repartidor)

    def get_capacidad(self, repartidor):
        return calcular_capacidad(self._cantidad(repartidor))

    def get_solicitudes_activas(self, repartidor):
        return self._cantidad(repartidor)

    def get_limite_solicitudes(self, _repartidor):
        return LIMITE_SOLICITUDES

    def get_puede_recibir_solicitudes(self, repartidor):
        return puede_recibir_solicitudes(repartidor, self._cantidad(repartidor))

    class Meta:
        model = Repartidor
        fields = (
            "id",
            "usuario",
            "empresa_id",
            "vehiculo",
            "estado_operativo",
            "capacidad",
            "solicitudes_activas",
            "limite_solicitudes",
            "puede_recibir_solicitudes",
            "activo",
            "creado_en",
            "actualizado_en",
        )


class SerializadorCreacionRepartidor(serializers.Serializer):
    usuario_id = serializers.UUIDField()
    empresa_id = serializers.UUIDField(required=False, allow_null=True)
    vehiculo_id = serializers.UUIDField(required=False, allow_null=True)


class SerializadorConsultaRepartidores(serializers.Serializer):
    empresa_id = serializers.UUIDField(required=False)
    estado_operativo = serializers.ChoiceField(
        choices=EstadoOperativoRepartidor.choices, required=False
    )
    capacidad = serializers.ChoiceField(
        choices=CapacidadRepartidor.choices, required=False
    )
    activo = serializers.BooleanField(required=False)


class SerializadorActualizacionOperacionRepartidor(serializers.Serializer):
    estado_operativo = serializers.ChoiceField(
        choices=EstadoOperativoRepartidor.choices, required=False
    )
    motivo = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate(self, atributos):
        if "capacidad" in self.initial_data:
            raise serializers.ValidationError(
                {"capacidad": "La capacidad se calcula automáticamente."}
            )
        if "estado_operativo" not in atributos:
            raise serializers.ValidationError(
                {"estado_operativo": "Debe enviar el estado operativo."}
            )
        return atributos
