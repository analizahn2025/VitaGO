from rest_framework import serializers


class SerializadorInicioSesion(serializers.Serializer):
    correo = serializers.EmailField(max_length=254)
    contrasena = serializers.CharField(
        max_length=128,
        trim_whitespace=False,
        write_only=True,
    )


class SerializadorRenovacionToken(serializers.Serializer):
    token_refresco = serializers.CharField(
        max_length=4096,
        trim_whitespace=False,
        write_only=True,
    )
