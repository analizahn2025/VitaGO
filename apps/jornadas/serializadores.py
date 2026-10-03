from rest_framework import serializers

from apps.jornadas.models import JornadaRepartidor
from apps.jornadas.opciones import EstadoJornada


class SerializadorJornada(serializers.ModelSerializer):
    kilometraje_disponible = serializers.SerializerMethodField()
    incidencias_disponibles = serializers.SerializerMethodField()

    class Meta:
        model = JornadaRepartidor
        fields = (
            "id",
            "repartidor_id",
            "estado",
            "iniciada_en",
            "finalizada_en",
            "latitud_inicio",
            "longitud_inicio",
            "latitud_fin",
            "longitud_fin",
            "kilometros_operativos",
            "kilometraje_disponible",
            "servicios_completados",
            "recolecciones_completadas",
            "entregas_completadas",
            "servicios_normales",
            "servicios_prioritarios",
            "minutos_activos",
            "incidencias_reportadas",
            "incidencias_disponibles",
            "creado_en",
            "actualizado_en",
        )

    def get_kilometraje_disponible(self, objeto):
        return False

    def get_incidencias_disponibles(self, objeto):
        return True


class SerializadorCoordenadasJornada(serializers.Serializer):
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

    def validate(self, atributos):
        tiene_latitud = atributos.get("latitud") is not None
        tiene_longitud = atributos.get("longitud") is not None
        if tiene_latitud != tiene_longitud:
            raise serializers.ValidationError(
                "La latitud y longitud deben enviarse juntas."
            )
        return atributos


class SerializadorConsultaJornadas(serializers.Serializer):
    repartidor_id = serializers.UUIDField(required=False)
    estado = serializers.ChoiceField(
        choices=EstadoJornada.choices,
        required=False,
    )
    desde = serializers.DateTimeField(required=False)
    hasta = serializers.DateTimeField(required=False)

    def validate(self, atributos):
        desde = atributos.get("desde")
        hasta = atributos.get("hasta")
        if desde and hasta and desde > hasta:
            raise serializers.ValidationError(
                {"hasta": "Debe ser posterior o igual a desde."}
            )
        return atributos
