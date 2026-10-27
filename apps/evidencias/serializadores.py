from rest_framework import serializers

from apps.evidencias.models import EvidenciaSolicitud
from apps.evidencias.opciones import TipoEvidenciaSolicitud


class SerializadorEvidenciaSolicitud(serializers.ModelSerializer):
    archivo_disponible = serializers.SerializerMethodField()
    estado_solicitud = serializers.CharField(source="solicitud.estado", read_only=True)

    class Meta:
        model = EvidenciaSolicitud
        fields = (
            "id",
            "solicitud_id",
            "estado_solicitud",
            "repartidor_id",
            "tipo",
            "temperatura_contenedor_c", "fuente_temperatura",
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
    temperatura_contenedor_c = serializers.DecimalField(max_digits=6, decimal_places=2, required=False)
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
    # Se conserva en el contrato, pero su valor lo decide el servicio.
    capturada_en = serializers.DateTimeField(read_only=True)
    notas = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )

    def validate(self, atributos):
        if "fuente_temperatura" in self.initial_data:
            raise serializers.ValidationError({"fuente_temperatura": "La fuente la determina el servidor."})
        if atributos["tipo"] == TipoEvidenciaSolicitud.FOTO_RECOLECCION:
            from apps.evidencias.temperaturas import validar_temperatura
            atributos["temperatura_contenedor_c"] = validar_temperatura(atributos.get("temperatura_contenedor_c"))
        elif "temperatura_contenedor_c" in atributos:
            raise serializers.ValidationError({"temperatura_contenedor_c": "Solo corresponde a la recolección."})
        return atributos

