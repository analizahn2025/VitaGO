from decimal import Decimal

from rest_framework import serializers

from apps.seguimiento.models import RegistroUbicacion, RevisionKilometraje
from apps.repartidores.opciones import EstadoOperativoRepartidor


class SerializadorConsultaMotoristasSeguimiento(serializers.Serializer):
    empresa_id = serializers.UUIDField(required=False)
    repartidor_id = serializers.UUIDField(required=False)
    estado_operativo = serializers.ChoiceField(choices=EstadoOperativoRepartidor.choices, required=False)
    en_almuerzo = serializers.BooleanField(required=False)
    con_servicios = serializers.BooleanField(required=False)

    def validate(self, atributos):
        desconocidos = set(self.initial_data) - set(self.fields) - {"pagina", "tamano_pagina"}
        if desconocidos:
            raise serializers.ValidationError({campo: "Filtro no permitido." for campo in sorted(desconocidos)})
        return atributos


class SerializadorUbicacionMotorista(serializers.ModelSerializer):
    recibida_en = serializers.DateTimeField(source="creado_en")

    class Meta:
        model = RegistroUbicacion
        fields = ("latitud", "longitud", "precision_metros", "velocidad_metros_segundo", "rumbo_grados", "registrada_en", "recibida_en", "es_operativo")


class SerializadorMotoristaSeguimiento(serializers.Serializer):
    repartidor_id = serializers.UUIDField()
    usuario_id = serializers.UUIDField()
    nombre = serializers.CharField()
    empresa_id = serializers.UUIDField(allow_null=True)
    jornada_id = serializers.UUIDField()
    fecha_operativa = serializers.DateField(allow_null=True)
    iniciada_en = serializers.DateTimeField()
    cierre_programado_en = serializers.DateTimeField()
    estado_operativo = serializers.ChoiceField(choices=EstadoOperativoRepartidor.choices)
    en_almuerzo = serializers.BooleanField()
    solicitudes_activas = serializers.IntegerField()
    tiene_servicios_activos = serializers.BooleanField()
    ubicacion = SerializadorUbicacionMotorista(allow_null=True)
    estado_ubicacion = serializers.ChoiceField(choices=("ACTUALIZADA", "DESACTUALIZADA", "SIN_PRECISION", "BAJA_PRECISION", "SIN_UBICACION"))
    ubicacion_vigente = serializers.BooleanField()
    antiguedad_segundos = serializers.FloatField(allow_null=True)


class SerializadorLlegadaDetectada(serializers.Serializer):
    evento_id = serializers.UUIDField()
    solicitud_id = serializers.UUIDField()
    estado = serializers.ChoiceField(choices=("AT_PICKUP", "AT_DESTINATION"))
    tipo_parada = serializers.ChoiceField(choices=("RECOLECCION", "ENTREGA"))
    detectada_en = serializers.DateTimeField()
    fuente = serializers.ChoiceField(choices=("GPS", "MANUAL"))
    pantalla = serializers.ChoiceField(choices=("RECOLECCION", "ENTREGA"))
    ruta = serializers.CharField()


class SerializadorRegistroUbicacionEntrada(serializers.Serializer):
    id_cliente = serializers.UUIDField()
    sesion_gps = serializers.UUIDField(required=False, allow_null=True)
    secuencia = serializers.IntegerField(min_value=1, max_value=9223372036854775807, required=False, allow_null=True)
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
    precision_metros = serializers.DecimalField(
        max_digits=8,
        decimal_places=2,
        min_value=0,
        required=False,
        allow_null=True,
    )
    velocidad_metros_segundo = serializers.DecimalField(
        max_digits=8,
        decimal_places=3,
        min_value=0,
        required=False,
        allow_null=True,
    )
    rumbo_grados = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        min_value=Decimal("0"),
        max_value=Decimal("359.99"),
        required=False,
        allow_null=True,
    )
    registrada_en = serializers.DateTimeField()

    def validate(self, atributos):
        if (atributos.get("sesion_gps") is None) != (atributos.get("secuencia") is None):
            raise serializers.ValidationError({"secuencia": "Debe enviarse junto con sesion_gps."})
        return atributos


class SerializadorSesionCierreGPS(serializers.Serializer):
    sesion_gps = serializers.UUIDField()
    ultima_secuencia = serializers.IntegerField(min_value=1, max_value=9223372036854775807)


class SerializadorConfirmacionGPS(serializers.Serializer):
    sesiones_gps = SerializadorSesionCierreGPS(many=True, allow_empty=True)

    def validate_sesiones_gps(self, sesiones):
        if len(sesiones) > 50:
            raise serializers.ValidationError("No puede confirmar más de 50 sesiones por cierre.")
        ids = [sesion["sesion_gps"] for sesion in sesiones]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("Las sesiones deben ser únicas.")
        return sesiones


class SerializadorConfirmacionMovimientoGPS(SerializadorConfirmacionGPS):
    movimiento_id = serializers.UUIDField(required=False)


class SerializadorLoteRegistrosUbicacion(serializers.Serializer):
    jornada_id = serializers.UUIDField()
    registros = SerializadorRegistroUbicacionEntrada(many=True)

    def validate_registros(self, registros):
        if not registros:
            raise serializers.ValidationError(
                "Debe enviar al menos un registro de ubicación."
            )
        if len(registros) > 200:
            raise serializers.ValidationError(
                "No puede enviar más de 200 registros por solicitud."
            )
        identificadores = [registro["id_cliente"] for registro in registros]
        if len(identificadores) != len(set(identificadores)):
            raise serializers.ValidationError(
                "Cada id_cliente debe ser único dentro del lote."
            )
        secuencias = [(r.get("sesion_gps"), r.get("secuencia")) for r in registros if r.get("sesion_gps")]
        if len(secuencias) != len(set(secuencias)):
            raise serializers.ValidationError("Cada secuencia debe ser única dentro de su sesión GPS.")
        return registros


class SerializadorRegistroUbicacion(serializers.ModelSerializer):
    class Meta:
        model = RegistroUbicacion
        fields = (
            "id", "id_cliente", "jornada_id", "repartidor_id", "latitud",
            "longitud", "precision_metros", "velocidad_metros_segundo",
            "rumbo_grados", "registrada_en", "es_operativo", "creado_en",
            "movimiento_envio_especial_id",
            "sesion_gps", "secuencia",
        )


class SerializadorSeguimientoSolicitud(serializers.Serializer):
    solicitud_id = serializers.UUIDField()
    estado = serializers.CharField()
    seguimiento_disponible = serializers.BooleanField()
    ubicacion = SerializadorRegistroUbicacion(allow_null=True)
    ubicacion_vigente = serializers.BooleanField()


class SerializadorRevisionKilometraje(serializers.ModelSerializer):
    class Meta:
        model = RevisionKilometraje
        fields = ("id", "jornada_id", "movimiento_especial_id", "numero", "motivo", "kilometros", "calidad", "creado_en")
