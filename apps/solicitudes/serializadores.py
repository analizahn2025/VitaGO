"""Serializadores HTTP del dominio de solicitudes."""

import re
from datetime import date
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
            "cantidad_tubos",
            "cantidad_frascos",
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


class SerializadorEntregaResumenDiario(SerializadorSolicitudResumen):
    class Meta(SerializadorSolicitudResumen.Meta):
        fields = SerializadorSolicitudResumen.Meta.fields + ("entregada_en",)


class SerializadorSolicitudDetalle(SerializadorSolicitudResumen):
    articulos_historicos = SerializadorArticuloSolicitud(source="articulos", many=True, read_only=True)
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
            "articulos_historicos",
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


class SerializadorCreacionSolicitud(serializers.Serializer):
    cantidad_tubos = serializers.IntegerField(min_value=0, max_value=2147483647, default=0)
    cantidad_frascos = serializers.IntegerField(min_value=0, max_value=2147483647, default=0)
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
    def validate(self, atributos):
        if "articulos" in self.initial_data:
            raise serializers.ValidationError({"articulos": "Los artículos fueron retirados. Declare únicamente tubos y frascos."})
        from apps.solicitudes.recipientes import validar_cantidades_recipientes
        validar_cantidades_recipientes(atributos["cantidad_tubos"], atributos["cantidad_frascos"])
        return atributos


class SerializadorActualizacionTubos(serializers.Serializer):
    cantidad_tubos = serializers.IntegerField(min_value=0, max_value=2147483647)
    motivo = serializers.CharField(max_length=1000, allow_blank=False)

    def validate(self, atributos):
        if "cantidad_frascos" in self.initial_data:
            raise serializers.ValidationError({"cantidad_frascos": "Use la ruta de carga para corregir tubos y frascos."})
        return atributos


class SerializadorActualizacionCarga(serializers.Serializer):
    cantidad_tubos = serializers.IntegerField(min_value=0, max_value=2147483647, required=False)
    cantidad_frascos = serializers.IntegerField(min_value=0, max_value=2147483647, required=False)
    motivo = serializers.CharField(max_length=1000, allow_blank=False)

    def validate(self, atributos):
        desconocidos = set(self.initial_data) - set(self.fields)
        if desconocidos:
            raise serializers.ValidationError({campo: "Campo no permitido." for campo in desconocidos})
        if not {"cantidad_tubos", "cantidad_frascos"} & atributos.keys():
            raise serializers.ValidationError({"detail": "Debe indicar tubos o frascos para corregir la carga."})
        return atributos


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
    fecha_operativa = serializers.DateField(
        required=False,
        input_formats=("%Y-%m-%d",),
    )

    def validate(self, atributos):
        texto = self.initial_data.get("fecha_operativa")
        if isinstance(texto, str) and not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}", texto
        ):
            raise serializers.ValidationError(
                {"fecha_operativa": "Use el formato AAAA-MM-DD."}
            )
        return atributos

    def validate_fecha_operativa(self, valor):
        if valor == date.max:
            raise serializers.ValidationError(
                "La fecha debe permitir calcular el inicio del día siguiente."
            )
        return valor


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
