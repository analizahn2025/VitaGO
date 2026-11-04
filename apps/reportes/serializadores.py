from calendar import monthrange
from datetime import date
import re

from rest_framework import serializers


class SerializadorConsultaReporte(serializers.Serializer):
    formato = serializers.ChoiceField(choices=("xlsx", "pdf"), default="xlsx")
    empresa_id = serializers.UUIDField(required=False)
    repartidor_id = serializers.UUIDField(required=False)
    activo = serializers.BooleanField(required=False)

    def validate(self, atributos):
        desconocidos = set(self.initial_data) - set(self.fields)
        if desconocidos:
            raise serializers.ValidationError({campo: "Filtro no permitido." for campo in sorted(desconocidos)})
        return atributos


class SerializadorConsultaReporteMotoristas(SerializadorConsultaReporte):
    periodo = serializers.ChoiceField(choices=("MENSUAL", "QUINCENAL"))
    mes = serializers.RegexField(r"\A[0-9]{4}-[0-9]{2}\Z", trim_whitespace=False, error_messages={"invalid": "Use el formato AAAA-MM."})
    quincena = serializers.ChoiceField(choices=("1", "2"), required=False)

    def validate(self, atributos):
        atributos = super().validate(atributos)
        try:
            anio, mes = map(int, atributos["mes"].split("-"))
            primero = date(anio, mes, 1)
            ultimo = date(anio, mes, monthrange(anio, mes)[1])
        except ValueError:
            raise serializers.ValidationError({"mes": "Indique un mes válido en formato AAAA-MM."})
        if atributos["periodo"] == "MENSUAL":
            if "quincena" in atributos:
                raise serializers.ValidationError({"quincena": "Solo se permite en reportes QUINCENALES."})
        else:
            if "quincena" not in atributos:
                raise serializers.ValidationError({"quincena": "Seleccione 1 (días 1–15) o 2 (día 16 al último del mes)."})
            if atributos["quincena"] == "1":
                ultimo = date(anio, mes, 15)
            else:
                primero = date(anio, mes, 16)
        if ultimo == date.max:
            raise serializers.ValidationError({"mes": "El período debe terminar antes de 9999-12-31."})
        return {**atributos, "fecha_desde": primero, "fecha_hasta": ultimo}


class SerializadorConsultaReporteServicios(SerializadorConsultaReporte):
    fecha = serializers.DateField(input_formats=("%Y-%m-%d",))

    def validate(self, atributos):
        atributos = super().validate(atributos)
        if atributos["fecha"] == date.max or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", str(self.initial_data["fecha"])):
            raise serializers.ValidationError({"fecha": "Use una fecha válida en formato AAAA-MM-DD anterior a 9999-12-31."})
        return atributos
