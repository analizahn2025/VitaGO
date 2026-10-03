from rest_framework import serializers

from apps.incidencias.models import (
    EventoIncidencia,
    EvidenciaIncidencia,
    Incidencia,
)
from apps.incidencias.opciones import EstadoIncidencia


class SerializadorEventoIncidencia(serializers.ModelSerializer):
    class Meta:
        model = EventoIncidencia
        fields = (
            "id",
            "tipo",
            "realizado_por_id",
            "estado_anterior",
            "estado_nuevo",
            "notas",
            "metadatos",
            "creado_en",
        )


class SerializadorIncidencia(serializers.ModelSerializer):
    eventos = SerializadorEventoIncidencia(many=True, read_only=True)

    class Meta:
        model = Incidencia
        fields = (
            "id",
            "jornada_id",
            "repartidor_id",
            "solicitud_id",
            "estado",
            "descripcion",
            "latitud",
            "longitud",
            "reportada_en",
            "revisada_por_id",
            "revisada_en",
            "cerrada_en",
            "eventos",
            "creado_en",
            "actualizado_en",
        )


class SerializadorCreacionIncidencia(serializers.Serializer):
    solicitud_id = serializers.UUIDField(required=False, allow_null=True)
    descripcion = serializers.CharField(allow_blank=False, trim_whitespace=True)
    latitud = serializers.DecimalField(
        max_digits=9,
        decimal_places=6,
        min_value=-90,
        max_value=90,
        required=False,
        allow_null=True,
    )
    longitud = serializers.DecimalField(
        max_digits=9,
        decimal_places=6,
        min_value=-180,
        max_value=180,
        required=False,
        allow_null=True,
    )
    reportada_en = serializers.DateTimeField()

    def validate(self, atributos):
        tiene_latitud = atributos.get("latitud") is not None
        tiene_longitud = atributos.get("longitud") is not None
        if tiene_latitud != tiene_longitud:
            raise serializers.ValidationError(
                "La latitud y longitud deben enviarse juntas."
            )
        return atributos


class SerializadorConsultaIncidencias(serializers.Serializer):
    estado = serializers.ChoiceField(
        choices=EstadoIncidencia.choices,
        required=False,
    )
    jornada_id = serializers.UUIDField(required=False)
    solicitud_id = serializers.UUIDField(required=False)
    repartidor_id = serializers.UUIDField(required=False)


class SerializadorRevisionIncidencia(serializers.Serializer):
    estado = serializers.ChoiceField(
        choices=(
            EstadoIncidencia.EN_REVISION,
            EstadoIncidencia.CERRADA,
        )
    )
    notas = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )


class SerializadorEvidenciaIncidencia(serializers.ModelSerializer):
    archivo_disponible = serializers.SerializerMethodField()

    class Meta:
        model = EvidenciaIncidencia
        fields = (
            "id",
            "incidencia_id",
            "repartidor_id",
            "tipo_contenido",
            "tamano_bytes",
            "latitud",
            "longitud",
            "capturada_en",
            "notas",
            "archivo_disponible",
            "creado_en",
        )

    def get_archivo_disponible(self, objeto):
        return bool(objeto.clave_almacenamiento)


class SerializadorRegistroEvidenciaIncidencia(serializers.Serializer):
    archivo = serializers.FileField(allow_empty_file=False)
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
    capturada_en = serializers.DateTimeField()
    notas = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )

