"""Contrato de lectura de rutas y paradas históricas."""

from rest_framework import serializers

from apps.rutas.models import ParadaVersionRuta, RutaRepartidor, VersionRuta


class SerializadorFiltrosRutas(serializers.Serializer):
    repartidor_id = serializers.UUIDField(required=False)
    estado = serializers.ChoiceField(
        choices=RutaRepartidor.Estado.choices, required=False
    )


class SerializadorRutaHistorica(serializers.ModelSerializer):
    cantidad_versiones = serializers.IntegerField(read_only=True)

    class Meta:
        model = RutaRepartidor
        fields = (
            "id", "repartidor_id", "jornada_id", "estado", "iniciada_en",
            "finalizada_en", "cantidad_versiones",
        )


class SerializadorVersionRuta(serializers.ModelSerializer):
    cantidad_paradas = serializers.IntegerField(read_only=True)

    class Meta:
        model = VersionRuta
        fields = (
            "id", "ruta_id", "numero", "motivo", "creada_en",
            "cantidad_paradas",
        )


class SerializadorParadaVersionRuta(serializers.ModelSerializer):
    ubicacion = serializers.SerializerMethodField()

    class Meta:
        model = ParadaVersionRuta
        fields = (
            "orden", "solicitud_id", "numero_solicitud", "prioridad",
            "modalidad", "estado_solicitud", "tipo", "ubicacion",
            "destino_especial", "presentacion_ruta",
        )

    def get_ubicacion(self, parada):
        if parada.ubicacion_id is None:
            return None
        return {
            "id": str(parada.ubicacion_id),
            "nombre": parada.nombre_ubicacion,
            "direccion": parada.direccion_ubicacion,
            "latitud": str(parada.latitud_ubicacion),
            "longitud": str(parada.longitud_ubicacion),
        }


class SerializadorVersionRutaDetalle(SerializadorVersionRuta):
    paradas = SerializadorParadaVersionRuta(many=True, read_only=True)

    class Meta(SerializadorVersionRuta.Meta):
        fields = SerializadorVersionRuta.Meta.fields + ("paradas",)
