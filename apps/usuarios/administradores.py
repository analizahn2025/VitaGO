from django.conf import settings
from django.contrib.auth.base_user import BaseUserManager

from apps.usuarios.opciones import EstadoUsuario


class AdministradorUsuarios(BaseUserManager):
    use_in_migrations = True

    def _crear_usuario(self, correo, contrasena=None, **campos_adicionales):
        if not correo:
            raise ValueError("El correo es obligatorio.")

        if settings.MODO_APLICACION == "CORPORATIVO" and contrasena:
            raise ValueError(
                "Los usuarios corporativos no pueden tener contraseñas locales."
            )

        correo = self.normalize_email(correo).casefold()
        usuario = self.model(correo=correo, **campos_adicionales)

        if contrasena:
            usuario.set_password(contrasena)
        else:
            usuario.password = None

        usuario.save(using=self._db)
        return usuario

    def create_user(self, correo, password=None, **campos_adicionales):
        """Integración requerida por el sistema de autenticación de Django."""
        campos_adicionales.setdefault("es_personal", False)
        campos_adicionales.setdefault("es_superusuario", False)
        return self._crear_usuario(correo, password, **campos_adicionales)

    def create_superuser(self, correo, password=None, **campos_adicionales):
        """Integración requerida por el comando createsuperuser de Django."""
        if settings.MODO_APLICACION == "CORPORATIVO":
            raise ValueError(
                "Los despliegues corporativos no usan superusuarios locales."
            )
        if not password:
            raise ValueError("La contraseña del superusuario es obligatoria.")

        campos_adicionales.setdefault("estado", EstadoUsuario.ACTIVO)
        campos_adicionales.setdefault("es_personal", True)
        campos_adicionales.setdefault("es_superusuario", True)

        if campos_adicionales.get("es_personal") is not True:
            raise ValueError("Un superusuario debe tener es_personal=True.")
        if campos_adicionales.get("es_superusuario") is not True:
            raise ValueError("Un superusuario debe tener es_superusuario=True.")

        return self._crear_usuario(correo, password, **campos_adicionales)
