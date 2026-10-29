from rest_framework import serializers

from apps.jornadas.models import AlmuerzoJornada, JornadaRepartidor
from apps.jornadas.horario import jornada_vigente
from apps.jornadas.opciones import EstadoJornada
from apps.seguimiento.serializadores import SerializadorConfirmacionGPS, SerializadorSesionCierreGPS


class SerializadorAlmuerzo(serializers.ModelSerializer):
    class Meta:
        model = AlmuerzoJornada
        fields = ("id", "iniciada_en", "finalizada_en", "finalizada_por_id", "motivo_cierre")


class SerializadorJornada(serializers.ModelSerializer):
    incidencias_disponibles = serializers.SerializerMethodField()
    puede_operar = serializers.SerializerMethodField()
    en_almuerzo = serializers.SerializerMethodField()
    almuerzos = SerializadorAlmuerzo(many=True, read_only=True)

    class Meta:
        model = JornadaRepartidor
        fields = (
            "id",
            "repartidor_id",
            "estado",
            "iniciada_en",
            "finalizada_en",
            "fecha_operativa", "cierre_programado_en", "puede_operar", "en_almuerzo", "almuerzos",
            "latitud_inicio",
            "longitud_inicio",
            "latitud_fin",
            "longitud_fin",
            "kilometros_operativos",
            "kilometraje_disponible",
            "calidad_kilometraje", "minutos_operativos",
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

    def get_incidencias_disponibles(self, objeto):
        return True

    def get_puede_operar(self, objeto):
        return jornada_vigente(objeto) and not self.get_en_almuerzo(objeto)

    def get_en_almuerzo(self, objeto):
        return jornada_vigente(objeto) and any(almuerzo.finalizada_en is None for almuerzo in objeto.almuerzos.all())


class SerializadorAccionAlmuerzo(serializers.Serializer):
    def validate(self, atributos):
        if self.initial_data:
            raise serializers.ValidationError({campo: "No se admiten parámetros; la hora la establece el servidor." for campo in self.initial_data})
        return atributos


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


class SerializadorCierreJornada(SerializadorCoordenadasJornada, SerializadorConfirmacionGPS):
    sesiones_gps = SerializadorSesionCierreGPS(many=True, required=False, allow_empty=True)
