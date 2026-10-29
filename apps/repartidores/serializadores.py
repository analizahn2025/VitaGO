import re
from datetime import date

from rest_framework import serializers

from apps.flota.serializadores import SerializadorVehiculo
from apps.repartidores.capacidad import (
    calcular_capacidad,
    puede_recibir_solicitudes,
    obtener_carga_tubos,
)
from apps.repartidores.models import Repartidor
from apps.repartidores.limites import obtener_limites_repartidor
from apps.repartidores.opciones import (
    CapacidadRepartidor,
    EstadoOperativoRepartidor,
)
from apps.usuarios.serializadores import SerializadorUsuarioPerfil
from apps.evidencias.models import EvidenciaSolicitud


class SerializadorConsultaResumenMotoristas(serializers.Serializer):
    empresa_id = serializers.UUIDField(required=False)
    repartidor_id = serializers.UUIDField(required=False)
    activo = serializers.BooleanField(required=False)
    fecha_operativa = serializers.DateField(required=False, input_formats=("%Y-%m-%d",))

    def validate_fecha_operativa(self, valor):
        texto = self.initial_data.get("fecha_operativa")
        if not isinstance(texto, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", texto) or valor == date.max:
            raise serializers.ValidationError("Use una fecha válida en formato AAAA-MM-DD anterior a 9999-12-31.")
        return valor

    def validate(self, atributos):
        desconocidos = set(self.initial_data) - set(self.fields) - {"pagina", "tamano_pagina"}
        if desconocidos:
            raise serializers.ValidationError({campo: "Filtro no permitido." for campo in sorted(desconocidos)})
        return atributos


class SerializadorResumenMotorista(serializers.Serializer):
    repartidor = serializers.JSONField()
    fecha_operativa = serializers.DateField()
    zona_horaria_operativa = serializers.CharField()
    periodo = serializers.JSONField()
    generado_en = serializers.DateTimeField()
    solicitudes = serializers.JSONField()
    tubos = serializers.JSONField()
    kilometraje = serializers.JSONField()
    temperaturas = serializers.JSONField()
    carga_actual = serializers.JSONField()


class SerializadorLecturaTemperaturaResumen(serializers.ModelSerializer):
    numero_solicitud = serializers.CharField(source="solicitud.numero")

    class Meta:
        model = EvidenciaSolicitud
        fields = ("id", "solicitud_id", "numero_solicitud", "temperatura_contenedor_c", "fuente_temperatura", "capturada_en")


class SerializadorRepartidor(serializers.ModelSerializer):
    en_almuerzo = serializers.SerializerMethodField()
    almuerzo_iniciado_en = serializers.SerializerMethodField()
    usuario = SerializadorUsuarioPerfil(read_only=True)
    vehiculo = SerializadorVehiculo(read_only=True)
    capacidad = serializers.SerializerMethodField()
    solicitudes_activas = serializers.SerializerMethodField()
    limite_solicitudes = serializers.SerializerMethodField()
    limite_tubos = serializers.SerializerMethodField()
    puede_recibir_solicitudes = serializers.SerializerMethodField()
    tubos_comprometidos = serializers.SerializerMethodField()
    tubos_en_transporte = serializers.SerializerMethodField()
    tubos_reservados = serializers.SerializerMethodField()
    tubos_disponibles = serializers.SerializerMethodField()
    solicitudes_sin_cantidad_tubos = serializers.SerializerMethodField()

    def _almuerzo(self, repartidor):
        if not hasattr(repartidor, "en_almuerzo"):
            from apps.jornadas.horario import anotar_jornada_y_almuerzo
            datos = anotar_jornada_y_almuerzo(Repartidor.objects.filter(pk=repartidor.pk)).values("en_almuerzo", "almuerzo_iniciado_en").get()
            repartidor.en_almuerzo = datos["en_almuerzo"]
            repartidor.almuerzo_iniciado_en = datos["almuerzo_iniciado_en"]
        return repartidor.almuerzo_iniciado_en

    def get_en_almuerzo(self, repartidor):
        self._almuerzo(repartidor)
        return repartidor.en_almuerzo

    def get_almuerzo_iniciado_en(self, repartidor):
        instante = self._almuerzo(repartidor)
        return serializers.DateTimeField().to_representation(instante) if instante else None

    def _carga(self, repartidor):
        if not hasattr(self, "_cargas_tubos"):
            self._cargas_tubos = {}
        if repartidor.pk not in self._cargas_tubos:
            self._cargas_tubos[repartidor.pk] = obtener_carga_tubos(repartidor)
        return self._cargas_tubos[repartidor.pk]

    def get_tubos_comprometidos(self, repartidor):
        return self._carga(repartidor)["tubos_comprometidos"]

    def get_tubos_en_transporte(self, repartidor):
        return self._carga(repartidor)["tubos_en_transporte"]

    def get_tubos_reservados(self, repartidor):
        carga = self._carga(repartidor)
        return carga["tubos_comprometidos"] - carga["tubos_en_transporte"]

    def get_tubos_disponibles(self, repartidor):
        carga = self._carga(repartidor)
        return 0 if carga["solicitudes_sin_cantidad_tubos"] else max(0, self._limites(repartidor)["limite_tubos"] - carga["tubos_comprometidos"])

    def _limites(self, repartidor):
        if not hasattr(self, "_limites_motoristas"):
            self._limites_motoristas = {}
        if repartidor.pk not in self._limites_motoristas:
            self._limites_motoristas[repartidor.pk] = obtener_limites_repartidor(repartidor)
        return self._limites_motoristas[repartidor.pk]

    def get_solicitudes_sin_cantidad_tubos(self, repartidor):
        return self._carga(repartidor)["solicitudes_sin_cantidad_tubos"]

    def _cantidad(self, repartidor):
        return self._carga(repartidor)["solicitudes_activas"]

    def get_capacidad(self, repartidor):
        return calcular_capacidad(self._cantidad(repartidor), **self._limites(repartidor), **self._carga(repartidor))

    def get_solicitudes_activas(self, repartidor):
        return self._cantidad(repartidor)

    def get_limite_solicitudes(self, repartidor):
        return self._limites(repartidor)["limite_solicitudes"]

    def get_limite_tubos(self, repartidor):
        return self._limites(repartidor)["limite_tubos"]

    def get_puede_recibir_solicitudes(self, repartidor):
        return puede_recibir_solicitudes(repartidor, self._cantidad(repartidor), carga=self._carga(repartidor))

    class Meta:
        model = Repartidor
        fields = (
            "id",
            "usuario",
            "empresa_id",
            "vehiculo",
            "estado_operativo",
            "en_almuerzo", "almuerzo_iniciado_en",
            "capacidad",
            "solicitudes_activas",
            "limite_solicitudes",
            "limite_tubos", "tubos_comprometidos", "tubos_en_transporte", "tubos_reservados",
            "tubos_disponibles", "solicitudes_sin_cantidad_tubos",
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
    en_almuerzo = serializers.BooleanField(required=False)
    cantidad_tubos = serializers.IntegerField(min_value=1, max_value=2147483647, required=False)
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
