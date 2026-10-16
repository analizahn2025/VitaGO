"""Serializadores HTTP del dominio de solicitudes."""

from decimal import Decimal

from rest_framework import serializers

from apps.organizaciones.models import Sucursal
from apps.solicitudes.models import (
    AsignacionSolicitud,
    ArticuloSolicitud,
    EventoSolicitud,
    MovimientoEnvioEspecial,
    Solicitud,
    TipoServicio,
)
from apps.solicitudes.opciones import (
    EstadoMovimientoEnvioEspecial,
    EstadoSolicitud,
    ModalidadSolicitud,
    PrioridadSolicitud,
)
from apps.usuarios.models import Usuario
from apps.seguimiento.serializadores import SerializadorConfirmacionGPS, SerializadorSesionCierreGPS


class SerializadorTipoServicio(serializers.ModelSerializer):
    class Meta:
        model = TipoServicio
        fields = ("id", "codigo", "nombre", "descripcion")


class SerializadorUbicacionSolicitud(serializers.Serializer):
    id = serializers.UUIDField()
    nombre = serializers.CharField()
    direccion = serializers.CharField()
    latitud = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitud = serializers.DecimalField(max_digits=9, decimal_places=6)


class SerializadorUbicacionOpcionSolicitud(serializers.Serializer):
    id = serializers.UUIDField()
    nombre = serializers.CharField()
    tipo_codigo = serializers.CharField(source="tipo_ubicacion.codigo")
    departamento = serializers.CharField(
        source="nivel_administrativo_1",
        allow_null=True,
    )
    municipio = serializers.CharField(
        source="nivel_administrativo_2",
        allow_null=True,
    )
    ciudad = serializers.CharField(source="localidad", allow_null=True)
    colonia = serializers.CharField(allow_null=True)
    direccion = serializers.CharField()
    latitud = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitud = serializers.DecimalField(max_digits=9, decimal_places=6)


class SerializadorPuntoCreacionSolicitud(serializers.Serializer):
    sucursal_id = serializers.UUIDField(allow_null=True)
    sucursal_nombre = serializers.CharField(allow_null=True)
    ubicacion = SerializadorUbicacionOpcionSolicitud()


class SerializadorArticuloSolicitud(serializers.ModelSerializer):
    class Meta:
        model = ArticuloSolicitud
        fields = (
            "id",
            "tipo_articulo",
            "descripcion",
            "cantidad",
            "codigo_referencia",
            "condicion_transporte",
            "notas",
        )


class SerializadorEventoSolicitud(serializers.ModelSerializer):
    class Meta:
        model = EventoSolicitud
        fields = (
            "id",
            "tipo",
            "realizado_por_id",
            "repartidor_id",
            "latitud",
            "longitud",
            "metadatos",
            "creado_en",
        )


class SerializadorAsignacionSolicitud(serializers.ModelSerializer):
    class Meta:
        model = AsignacionSolicitud
        fields = (
            "id",
            "repartidor_id",
            "asignada_por_id",
            "tipo",
            "estado",
            "asignada_en",
            "aceptada_en",
            "finalizada_en",
            "motivo",
        )


class SerializadorMovimientoEnvioEspecial(serializers.ModelSerializer):
    class Meta:
        model = MovimientoEnvioEspecial
        fields = (
            "id",
            "repartidor_id",
            "jornada_id",
            "estado",
            "iniciada_en",
            "finalizada_en",
            "latitud_inicio",
            "longitud_inicio",
            "latitud_fin",
            "longitud_fin",
            "kilometros_recorridos",
            "registros_considerados",
            "registros_descartados",
            "calidad_kilometraje",
            "motivo_cierre",
        )


class SerializadorSolicitanteSolicitud(serializers.ModelSerializer):
    class Meta:
        model = Usuario
        fields = ("id", "nombres", "apellidos")


class SerializadorSucursalSolicitud(serializers.ModelSerializer):
    class Meta:
        model = Sucursal
        fields = ("id", "nombre")


class SerializadorSolicitudResumen(serializers.ModelSerializer):
    sucursal = SerializadorSucursalSolicitud(read_only=True)
    solicitante = SerializadorSolicitanteSolicitud(
        source="solicitada_por", read_only=True
    )
    tipo_servicio = SerializadorTipoServicio(read_only=True)
    origen = SerializadorUbicacionSolicitud(read_only=True)
    destino = SerializadorUbicacionSolicitud(read_only=True, allow_null=True)
    presentacion_ruta = serializers.SerializerMethodField()
    kilometros_envio_especial = serializers.SerializerMethodField()

    def get_presentacion_ruta(self, solicitud):
        return (
            "SOLO_KILOMETROS"
            if solicitud.modalidad == ModalidadSolicitud.ESPECIAL
            else "MAPA"
        )

    def get_kilometros_envio_especial(self, solicitud):
        movimientos = list(solicitud.movimientos_especiales.all())
        if not movimientos or any(m.estado != EstadoMovimientoEnvioEspecial.FINALIZADO for m in movimientos):
            return None
        return format(sum((m.kilometros_recorridos for m in movimientos), Decimal("0")), ".3f")

    class Meta:
        model = Solicitud
        fields = (
            "id",
            "numero",
            "empresa_id",
            "sucursal_id",
            "sucursal",
            "solicitada_por_id",
            "solicitante",
            "repartidor_asignado_id",
            "prioridad",
            "modalidad",
            "tipo_servicio",
            "origen",
            "destino",
            "destino_especial",
            "presentacion_ruta",
            "kilometros_envio_especial",
            "estado",
            "reasignacion_pendiente",
            "cerrada_en",
            "motivo_cierre",
            "creado_en",
        )


class SerializadorSolicitudDetalle(SerializadorSolicitudResumen):
    articulos = SerializadorArticuloSolicitud(many=True, read_only=True)
    eventos = SerializadorEventoSolicitud(many=True, read_only=True)
    asignaciones = SerializadorAsignacionSolicitud(many=True, read_only=True)
    movimiento_especial = serializers.SerializerMethodField()
    movimientos_especiales = SerializadorMovimientoEnvioEspecial(many=True, read_only=True)

    def get_movimiento_especial(self, solicitud):
        try:
            movimiento = solicitud.movimiento_especial
        except MovimientoEnvioEspecial.DoesNotExist:
            return None
        return SerializadorMovimientoEnvioEspecial(movimiento).data

    class Meta(SerializadorSolicitudResumen.Meta):
        fields = SerializadorSolicitudResumen.Meta.fields + (
            "notas",
            "articulos",
            "eventos",
            "asignaciones",
            "movimiento_especial",
            "movimientos_especiales",
            "asignada_en",
            "llegada_recoleccion_en",
            "recolectada_en",
            "llegada_destino_en",
            "entregada_en",
            "cancelada_en",
            "actualizado_en",
        )


class SerializadorArticuloCreacion(serializers.Serializer):
    tipo_articulo = serializers.CharField(max_length=100)
    descripcion = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    cantidad = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        default=Decimal("1"),
    )
    codigo_referencia = serializers.CharField(
        max_length=120,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    condicion_transporte = serializers.CharField(
        max_length=200,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    notas = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )


class SerializadorCreacionSolicitud(serializers.Serializer):
    empresa_id = serializers.UUIDField()
    sucursal_id = serializers.UUIDField(required=False, allow_null=True)
    prioridad = serializers.ChoiceField(choices=PrioridadSolicitud.choices)
    modalidad = serializers.ChoiceField(
        choices=ModalidadSolicitud.choices,
        required=False,
        allow_null=True,
    )
    tipo_servicio_id = serializers.UUIDField()
    origen_id = serializers.UUIDField()
    destino_id = serializers.UUIDField(required=False, allow_null=True)
    destino_especial = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    notas = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    articulos = SerializadorArticuloCreacion(many=True, allow_empty=False)


class SerializadorConsultaSolicitudes(serializers.Serializer):
    empresa_id = serializers.UUIDField(required=False)
    sucursal_id = serializers.UUIDField(required=False)
    sin_sucursal = serializers.BooleanField(required=False)
    solicitada_por_id = serializers.UUIDField(required=False)
    estado = serializers.ChoiceField(
        choices=EstadoSolicitud.choices,
        required=False,
    )
    prioridad = serializers.ChoiceField(
        choices=PrioridadSolicitud.choices,
        required=False,
    )
    modalidad = serializers.ChoiceField(
        choices=ModalidadSolicitud.choices,
        required=False,
    )

    def validate(self, atributos):
        if atributos.get("sucursal_id") and atributos.get("sin_sucursal"):
            raise serializers.ValidationError(
                {"sin_sucursal": "No puede combinarse con sucursal_id."}
            )
        return atributos


class SerializadorConsultaAgrupacionesSolicitudes(serializers.Serializer):
    por = serializers.ChoiceField(choices=("sucursal", "solicitante"))
    empresa_id = serializers.UUIDField(required=False)


class SerializadorConsultaOpcionesCreacion(serializers.Serializer):
    empresa_id = serializers.UUIDField()
    sucursal_id = serializers.UUIDField(required=False, allow_null=True)
    modalidad = serializers.ChoiceField(
        choices=ModalidadSolicitud.choices,
        required=False,
    )
    origen_id = serializers.UUIDField(required=False)


class SerializadorConsultaResumenSolicitante(serializers.Serializer):
    empresa_id = serializers.UUIDField(required=False)
    sucursal_id = serializers.UUIDField(required=False)


class SerializadorAsignacionManualSolicitud(serializers.Serializer):
    repartidor_id = serializers.UUIDField()
    motivo = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )


class SerializadorTransicionSolicitud(SerializadorConfirmacionGPS):
    sesiones_gps = SerializadorSesionCierreGPS(many=True, required=False, allow_empty=True)
    estado_destino = serializers.ChoiceField(choices=EstadoSolicitud.choices)
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
    motivo = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )

    def validate(self, atributos):
        tiene_latitud = atributos.get("latitud") is not None
        tiene_longitud = atributos.get("longitud") is not None
        if tiene_latitud != tiene_longitud:
            raise serializers.ValidationError(
                "La latitud y longitud deben enviarse juntas."
            )
        estados_con_motivo = {
            EstadoSolicitud.CANCELADA,
            EstadoSolicitud.RECOLECCION_FALLIDA,
            EstadoSolicitud.ENTREGA_FALLIDA,
        }
        if (
            atributos.get("estado_destino") in estados_con_motivo
            and not (atributos.get("motivo") or "").strip()
        ):
            raise serializers.ValidationError(
                {"motivo": "Debe indicar el motivo de esta transición."}
            )
        return atributos
