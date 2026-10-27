"""Errores de dominio del proceso de autenticación."""


class ErrorAutenticacion(Exception):
    """Error esperado que puede convertirse en una respuesta HTTP segura."""

    codigo = "autenticacion_invalida"


class CredencialesInvalidas(ErrorAutenticacion):
    codigo = "credenciales_invalidas"

    def __init__(self):
        super().__init__("Credenciales inválidas.")


class LimiteIntentosInicioSesion(ErrorAutenticacion):
    codigo = "limite_intentos_inicio_sesion"

    def __init__(self, segundos_espera):
        self.segundos_espera = segundos_espera
        super().__init__("Se alcanzó el límite de intentos de inicio de sesión. Intente más tarde.")


class TokenRefrescoInvalido(ErrorAutenticacion):
    codigo = "token_refresco_invalido"

    def __init__(self, mensaje="El token de refresco no es válido."):
        super().__init__(mensaje)


class SesionNoDisponible(ErrorAutenticacion):
    codigo = "sesion_no_disponible"

    def __init__(self, mensaje="La sesión no está disponible."):
        super().__init__(mensaje)
