from datetime import date
import re

from rest_framework import serializers


class SerializadorConsultaReporteMotoristas(serializers.Serializer):
    formato = serializers.ChoiceField(choices=("xlsx", "pdf"), default="xlsx")
    empresa_id = serializers.UUIDField(required=False)
    repartidor_id = serializers.UUIDField(required=False)
    activo = serializers.BooleanField(required=False)
    fecha_desde = serializers.DateField(required=False, input_formats=("%Y-%m-%d",))
    fecha_hasta = serializers.DateField(required=False, input_formats=("%Y-%m-%d",))

    def validate(self, atributos):
        desconocidos = set(self.initial_data) - set(self.fields)
        if desconocidos:
            raise serializers.ValidationError({campo: "Filtro no permitido." for campo in sorted(desconocidos)})
        for campo in ("fecha_desde", "fecha_hasta"):
            if campo in atributos and (atributos[campo] == date.max or not re.fullmatch(
                r"[0-9]{4}-[0-9]{2}-[0-9]{2}", str(self.initial_data[campo]),
            )):
                raise serializers.ValidationError({campo: "Use una fecha válida en formato AAAA-MM-DD anterior a 9999-12-31."})
        desde = atributos.get("fecha_desde") or atributos.get("fecha_hasta")
        hasta = atributos.get("fecha_hasta") or desde
        if desde:
            if hasta < desde:
                raise serializers.ValidationError({"fecha_hasta": "Debe ser igual o posterior a fecha_desde."})
            if (hasta - desde).days >= 31:
                raise serializers.ValidationError({"fecha_hasta": "El reporte admite como máximo 31 días. Reduzca el período."})
            atributos.update(fecha_desde=desde, fecha_hasta=hasta)
        return atributos
