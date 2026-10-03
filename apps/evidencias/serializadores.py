from rest_framework import serializers

from apps.evidencias.models import EvidenciaSolicitud
from apps.evidencias.opciones import TipoEvidenciaSolicitud


class SerializadorEvidenciaSolicitud(serializers.ModelSerializer):
    archivo_disponible = serializers.SerializerMethodField()

    class Meta:
        model = EvidenciaSolicitud
        fields = (
            "id",
            "solicitud_id",
            "repartidor_id",
            "tipo",
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


class SerializadorRegistroEvidencia(serializers.Serializer):
    tipo = serializers.ChoiceField(choices=TipoEvidenciaSolicitud.choices)
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

