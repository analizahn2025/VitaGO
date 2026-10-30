"""Contratos de empresas, sucursales y límites compartidos de motoristas."""

from django.conf import settings
from rest_framework import serializers

from apps.organizaciones.models import Empresa, Sucursal
from apps.repartidores.limites import limites_de_configuracion, obtener_configuracion_red


class SerializadorPaisOrganizacion(serializers.Serializer):
    id = serializers.UUIDField()
    iso2 = serializers.CharField()
    nombre = serializers.CharField()
    codigo_moneda = serializers.CharField()
    zona_horaria_predeterminada = serializers.CharField()


class SerializadorLimitesMotoristas(serializers.Serializer):
    limite_tubos = serializers.IntegerField(source="limite_tubos_por_motorista", read_only=True)
    limite_frascos = serializers.IntegerField(source="limite_frascos_por_motorista", read_only=True)
    limite_solicitudes = serializers.IntegerField(source="limite_solicitudes_por_motorista", read_only=True)

class SerializadorConfiguracionLimitesMotoristas(serializers.Serializer):
    limite_tubos = serializers.IntegerField(min_value=1, max_value=2147483647, required=False)
    limite_frascos = serializers.IntegerField(min_value=1, max_value=2147483647, required=False)
    limite_solicitudes = serializers.IntegerField(min_value=1, max_value=5, required=False)
    motivo = serializers.CharField(max_length=1000, required=False, allow_blank=True)

    def validate(self, atributos):
        desconocidos = set(self.initial_data) - set(self.fields)
        if desconocidos:
            raise serializers.ValidationError({campo: "Campo no permitido." for campo in sorted(desconocidos)})
        if not ({"limite_tubos", "limite_frascos", "limite_solicitudes"} & atributos.keys()):
            raise serializers.ValidationError({"detail": "Debe indicar al menos un límite."})
        return atributos


class SerializadorEmpresa(serializers.ModelSerializer):
    pais = SerializadorPaisOrganizacion(read_only=True)
    limites_motoristas = serializers.SerializerMethodField()

    def get_limites_motoristas(self, empresa):
        if settings.MODO_APLICACION == "EXTERNO":
            if not hasattr(self, "_limites_red"):
                self._limites_red = limites_de_configuracion(obtener_configuracion_red())
            return {"alcance": "RED", **self._limites_red}
        return {"alcance": "EMPRESA", **limites_de_configuracion(empresa)}

    class Meta:
        model = Empresa
        fields = (
            "id",
            "nombre",
            "razon_social",
            "identificacion_fiscal",
            "telefono",
            "correo",
            "pais",
            "estado",
            "limites_motoristas",
        )


class SerializadorTipoUbicacionResumen(serializers.Serializer):
    id = serializers.UUIDField()
    codigo = serializers.CharField()
    nombre = serializers.CharField()


class SerializadorUbicacionResumen(serializers.Serializer):
    id = serializers.UUIDField()
    nombre = serializers.CharField()
    tipo_ubicacion = SerializadorTipoUbicacionResumen()
    direccion = serializers.CharField()
    latitud = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitud = serializers.DecimalField(max_digits=9, decimal_places=6)
    estado = serializers.CharField()


class SerializadorSucursal(serializers.ModelSerializer):
    ubicacion = SerializadorUbicacionResumen(read_only=True)

    class Meta:
        model = Sucursal
        fields = (
            "id",
            "empresa_id",
            "nombre",
            "codigo",
            "telefono",
            "correo",
            "estado",
            "ubicacion",
        )


class SerializadorCreacionSucursal(serializers.Serializer):
    nombre = serializers.CharField(max_length=200)
    codigo = serializers.CharField(
        max_length=64,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    ubicacion_id = serializers.UUIDField()
    telefono = serializers.CharField(
        max_length=32,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    correo = serializers.EmailField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )
