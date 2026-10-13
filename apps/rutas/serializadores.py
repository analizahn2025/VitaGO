"""Contrato HTTP de la vista operativa de paradas pendientes."""

from rest_framework import serializers

from apps.solicitudes.opciones import (
    EstadoSolicitud,
    ModalidadSolicitud,
    PrioridadSolicitud,
)
from apps.solicitudes.serializadores import SerializadorUbicacionSolicitud


class SerializadorParadaRuta(serializers.Serializer):
    orden = serializers.IntegerField(min_value=1)
    solicitud_id = serializers.UUIDField()
    numero_solicitud = serializers.CharField()
    prioridad = serializers.ChoiceField(choices=PrioridadSolicitud.choices)
    modalidad = serializers.ChoiceField(
        choices=ModalidadSolicitud.choices, allow_null=True
    )
    estado_solicitud = serializers.ChoiceField(choices=EstadoSolicitud.choices)
    tipo = serializers.ChoiceField(
        choices=("RECOLECCION", "ENTREGA", "ENVIO_ESPECIAL")
    )
    ubicacion = SerializadorUbicacionSolicitud(allow_null=True)
    destino_especial = serializers.CharField(allow_null=True)
    presentacion_ruta = serializers.ChoiceField(
        choices=("MAPA", "SOLO_KILOMETROS")
    )


class SerializadorMiRuta(serializers.Serializer):
    repartidor_id = serializers.UUIDField()
    jornada_id = serializers.UUIDField(allow_null=True)
    ruta_id = serializers.UUIDField(allow_null=True)
    version_actual = serializers.IntegerField(allow_null=True, min_value=1)
    orden_tipo = serializers.ChoiceField(choices=("ASIGNACION",))
    ruta_calculada = serializers.BooleanField()
    proxima_parada = SerializadorParadaRuta(allow_null=True)
    paradas = SerializadorParadaRuta(many=True)
    navegacion = serializers.JSONField(allow_null=True)
    ruta_vial = serializers.JSONField()


class SerializadorCalcularRuta(serializers.Serializer):
    version_actual = serializers.IntegerField(min_value=1)
    reintentar = serializers.BooleanField(default=False)

    def to_internal_value(self, data):
        if isinstance(data, dict):
            desconocidos = set(data) - {"version_actual", "reintentar"}
            if desconocidos:
                raise serializers.ValidationError({campo: "Campo no permitido." for campo in desconocidos})
        return super().to_internal_value(data)
