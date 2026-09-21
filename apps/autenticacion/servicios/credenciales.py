"""Validación de credenciales locales para VitaGo Network."""

from django.contrib.auth.hashers import make_password

from apps.autenticacion.excepciones import CredencialesInvalidas
from apps.usuarios.models import Usuario


def autenticar_usuario_externo(correo, contrasena):
    correo_normalizado = Usuario.objetos.normalize_email(correo).casefold()

    try:
        usuario = Usuario.objetos.get(correo__iexact=correo_normalizado)
    except Usuario.DoesNotExist as exc:
        # Conserva un costo criptográfico similar y reduce enumeración por tiempo.
        make_password(contrasena)
        raise CredencialesInvalidas() from exc

    if not usuario.has_usable_password():
        make_password(contrasena)
        raise CredencialesInvalidas()

    contrasena_valida = usuario.check_password(contrasena)
    if not contrasena_valida or not usuario.is_active:
        raise CredencialesInvalidas()

    return usuario
