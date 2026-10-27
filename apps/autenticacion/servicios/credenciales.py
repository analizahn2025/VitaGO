"""Validación de credenciales del proveedor local de VitaGo."""

import json
from datetime import timedelta
from math import ceil

from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from apps.autenticacion.excepciones import CredencialesInvalidas, LimiteIntentosInicioSesion
from apps.autenticacion.models import ControlIntentosInicioSesion
from apps.usuarios.models import Usuario


LIMITE_INTENTOS = 10
VENTANA_INTENTOS = timedelta(minutes=15)


def autenticar_usuario_local(correo, contrasena, direccion_ip=None):
    """Serializa intentos del mismo correo/IP sin suspender la cuenta.

    El error de credenciales se propaga después de confirmar su contador.
    La sesión se crea fuera de esta transacción; otros errores no suman fallos.
    """
    correo_normalizado = Usuario.objetos.normalize_email(correo).casefold()
    huella = salted_hmac(
        "vitago.inicio_sesion", json.dumps([correo_normalizado, direccion_ip]),
        algorithm="sha256",
    ).hexdigest()
    error = None
    usuario = None
    with transaction.atomic():
        control, _ = ControlIntentosInicioSesion.objects.select_for_update().get_or_create(
            huella=huella, defaults={"ventana_iniciada_en": timezone.now()},
        )
        # Leer el reloj tras adquirir el bloqueo: una petición pudo esperar.
        ahora = timezone.now()
        if ahora >= control.ventana_iniciada_en + VENTANA_INTENTOS:
            control.intentos_fallidos = 0
        if control.intentos_fallidos >= LIMITE_INTENTOS:
            restante = control.ventana_iniciada_en + VENTANA_INTENTOS - ahora
            raise LimiteIntentosInicioSesion(max(1, ceil(restante.total_seconds())))
        if control.intentos_fallidos == 0:
            control.ventana_iniciada_en = ahora
        try:
            usuario = _validar_credenciales(correo_normalizado, contrasena)
        except CredencialesInvalidas as exc:
            control.intentos_fallidos += 1
            error = exc
        else:
            control.intentos_fallidos = 0
        control.save(update_fields=("intentos_fallidos", "ventana_iniciada_en", "actualizado_en"))
    if error is not None:
        raise error
    return usuario


def _validar_credenciales(correo_normalizado, contrasena):
    try:
        usuario = Usuario.objetos.get(correo=correo_normalizado)
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
