from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.nucleo.models import ModeloUUIDConMarcasDeTiempo
from apps.usuarios.administradores import AdministradorUsuarios
from apps.usuarios.opciones import EstadoUsuario, TipoAlcanceRol


class Usuario(ModeloUUIDConMarcasDeTiempo, AbstractBaseUser):
    password = models.CharField(
        _("contraseña"),
        max_length=128,
        null=True,
        blank=True,
        db_column="hash_contrasena",
    )
    last_login = models.DateTimeField(
        _("último acceso"),
        blank=True,
        null=True,
        db_column="ultimo_acceso",
    )
    identificador_autenticacion_externa = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
    )
    nombres = models.CharField(max_length=150)
    apellidos = models.CharField(max_length=150)
    correo = models.EmailField(unique=True)
    telefono = models.CharField(max_length=32, null=True, blank=True)
    empresa = models.ForeignKey(
        "organizaciones.Empresa",
        on_delete=models.PROTECT,
        related_name="usuarios",
        null=True,
        blank=True,
    )
    sucursal = models.ForeignKey(
        "organizaciones.Sucursal",
        on_delete=models.PROTECT,
        related_name="usuarios",
        null=True,
        blank=True,
    )
    estado = models.CharField(
        max_length=16,
        choices=EstadoUsuario.choices,
        default=EstadoUsuario.ACTIVO,
    )
    es_personal = models.BooleanField(default=False)
    es_superusuario = models.BooleanField(default=False)

    objetos = AdministradorUsuarios()

    USERNAME_FIELD = "correo"
    EMAIL_FIELD = "correo"
    REQUIRED_FIELDS = ["nombres", "apellidos"]

    class Meta:
        db_table = "usuarios"
        ordering = ("correo",)
        indexes = [
            models.Index(
                fields=("empresa", "estado"),
                name="usuarios_empresa_estado_idx",
            ),
            models.Index(
                fields=("sucursal", "estado"),
                name="usuarios_sucursal_estado_idx",
            ),
            models.Index(fields=("estado",), name="usuarios_estado_idx"),
        ]
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"

    @property
    def is_active(self):
        return self.estado == EstadoUsuario.ACTIVO

    @property
    def is_staff(self):
        return self.es_personal

    @property
    def is_superuser(self):
        return self.es_superusuario

    def clean(self):
        super().clean()
        self.correo = self.__class__.objetos.normalize_email(self.correo).casefold()
        self.identificador_autenticacion_externa = (
            self.identificador_autenticacion_externa or None
        )

        if self.sucursal_id:
            if not self.empresa_id:
                raise ValidationError(
                    {"empresa": "La empresa es obligatoria al elegir una sucursal."}
                )

            id_empresa_sucursal = self.sucursal.empresa_id
            if id_empresa_sucursal != self.empresa_id:
                raise ValidationError(
                    {"sucursal": "La sucursal debe pertenecer a la empresa elegida."}
                )

        if (
            settings.PROVEEDOR_AUTENTICACION == "JWT_CORPORATIVO"
            and self.password
            and self.has_usable_password()
        ):
            raise ValidationError(
                {
                    "password": (
                        "Los usuarios corporativos no pueden tener "
                        "contraseñas locales."
                    )
                }
            )

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def get_full_name(self):
        return f"{self.nombres} {self.apellidos}".strip()

    def get_short_name(self):
        return self.nombres

    def has_perm(self, perm, obj=None):
        return self.is_active and self.es_superusuario

    def has_module_perms(self, app_label):
        return self.is_active and self.es_superusuario

    def __str__(self):
        return self.correo


class Rol(ModeloUUIDConMarcasDeTiempo):
    codigo = models.CharField(max_length=80, unique=True)
    nombre = models.CharField(max_length=150)
    descripcion = models.TextField(null=True, blank=True)
    activo = models.BooleanField(default=True)
    permite_alcance_global = models.BooleanField(default=False)
    permite_alcance_empresa = models.BooleanField(default=False)
    permite_alcance_sucursal = models.BooleanField(default=False)

    objetos = models.Manager()

    class Meta:
        db_table = "roles"
        ordering = ("nombre",)
        verbose_name = "rol"
        verbose_name_plural = "roles"

    def clean(self):
        super().clean()
        self.codigo = self.codigo.strip().upper()
        if not any(
            (
                self.permite_alcance_global,
                self.permite_alcance_empresa,
                self.permite_alcance_sucursal,
            )
        ):
            raise ValidationError(
                {
                    "permite_alcance_global": (
                        "El rol debe permitir al menos un tipo de alcance."
                    )
                }
            )

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.nombre


class Permiso(ModeloUUIDConMarcasDeTiempo):
    codigo = models.CharField(max_length=120, unique=True)
    nombre = models.CharField(max_length=150)
    descripcion = models.TextField(null=True, blank=True)
    activo = models.BooleanField(default=True)

    roles = models.ManyToManyField(
        Rol,
        through="PermisoRol",
        related_name="permisos",
    )

    objetos = models.Manager()

    class Meta:
        db_table = "permisos"
        ordering = ("codigo",)
        verbose_name = "permiso"
        verbose_name_plural = "permisos"

    def clean(self):
        super().clean()
        self.codigo = self.codigo.strip().casefold()

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.codigo


class PermisoRol(ModeloUUIDConMarcasDeTiempo):
    rol = models.ForeignKey(
        Rol,
        on_delete=models.PROTECT,
        related_name="asignaciones_permisos",
    )
    permiso = models.ForeignKey(
        Permiso,
        on_delete=models.PROTECT,
        related_name="asignaciones_roles",
    )
    activo = models.BooleanField(default=True)

    objetos = models.Manager()

    class Meta:
        db_table = "permisos_rol"
        ordering = ("rol_id", "permiso_id")
        constraints = [
            models.UniqueConstraint(
                fields=("rol", "permiso"),
                name="permisos_rol_relacion_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=("rol", "activo"),
                name="permisos_rol_activo_idx",
            ),
        ]
        verbose_name = "permiso de rol"
        verbose_name_plural = "permisos de roles"

    def __str__(self):
        return f"{self.rol.codigo} - {self.permiso.codigo}"


class RolUsuario(ModeloUUIDConMarcasDeTiempo):
    usuario = models.ForeignKey(
        Usuario,
        on_delete=models.PROTECT,
        related_name="asignaciones_roles",
    )
    rol = models.ForeignKey(
        Rol,
        on_delete=models.PROTECT,
        related_name="asignaciones_usuarios",
    )
    tipo_alcance = models.CharField(
        max_length=16,
        choices=TipoAlcanceRol.choices,
    )
    empresa = models.ForeignKey(
        "organizaciones.Empresa",
        on_delete=models.PROTECT,
        related_name="asignaciones_roles_usuarios",
        null=True,
        blank=True,
    )
    sucursal = models.ForeignKey(
        "organizaciones.Sucursal",
        on_delete=models.PROTECT,
        related_name="asignaciones_roles_usuarios",
        null=True,
        blank=True,
    )
    activo = models.BooleanField(default=True)
    asignado_por = models.ForeignKey(
        Usuario,
        on_delete=models.PROTECT,
        related_name="roles_asignados",
        null=True,
        blank=True,
    )
    asignado_en = models.DateTimeField(default=timezone.now)
    revocado_por = models.ForeignKey(
        Usuario,
        on_delete=models.PROTECT,
        related_name="roles_revocados",
        null=True,
        blank=True,
    )
    revocado_en = models.DateTimeField(null=True, blank=True)

    objetos = models.Manager()

    class Meta:
        db_table = "roles_usuario"
        ordering = ("usuario_id", "rol_id", "asignado_en")
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        tipo_alcance=TipoAlcanceRol.GLOBAL,
                        empresa__isnull=True,
                        sucursal__isnull=True,
                    )
                    | models.Q(
                        tipo_alcance=TipoAlcanceRol.EMPRESA,
                        empresa__isnull=False,
                        sucursal__isnull=True,
                    )
                    | models.Q(
                        tipo_alcance=TipoAlcanceRol.SUCURSAL,
                        empresa__isnull=False,
                        sucursal__isnull=False,
                    )
                ),
                name="rol_usr_alcance_valido_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(activo=True, revocado_en__isnull=True)
                    | models.Q(activo=False, revocado_en__isnull=False)
                ),
                name="rol_usr_revocacion_valida_ck",
            ),
            models.UniqueConstraint(
                fields=("usuario", "rol"),
                condition=models.Q(
                    tipo_alcance=TipoAlcanceRol.GLOBAL,
                    activo=True,
                ),
                name="rol_usr_global_activo_uniq",
            ),
            models.UniqueConstraint(
                fields=("usuario", "rol", "empresa"),
                condition=models.Q(
                    tipo_alcance=TipoAlcanceRol.EMPRESA,
                    activo=True,
                ),
                name="rol_usr_empresa_activo_uniq",
            ),
            models.UniqueConstraint(
                fields=("usuario", "rol", "sucursal"),
                condition=models.Q(
                    tipo_alcance=TipoAlcanceRol.SUCURSAL,
                    activo=True,
                ),
                name="rol_usr_sucursal_activo_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=("usuario", "activo"),
                name="rol_usr_usuario_activo_idx",
            ),
            models.Index(
                fields=("empresa", "activo"),
                name="rol_usr_empresa_activo_idx",
            ),
            models.Index(
                fields=("sucursal", "activo"),
                name="rol_usr_sucursal_activo_idx",
            ),
        ]
        verbose_name = "rol de usuario"
        verbose_name_plural = "roles de usuarios"

    def clean(self):
        super().clean()
        errores = {}

        if self.rol_id:
            alcance_permitido = {
                TipoAlcanceRol.GLOBAL: self.rol.permite_alcance_global,
                TipoAlcanceRol.EMPRESA: self.rol.permite_alcance_empresa,
                TipoAlcanceRol.SUCURSAL: self.rol.permite_alcance_sucursal,
            }.get(self.tipo_alcance, False)
            if not alcance_permitido:
                errores["tipo_alcance"] = (
                    "El rol no permite el tipo de alcance seleccionado."
                )

        if self.tipo_alcance == TipoAlcanceRol.GLOBAL:
            if self.empresa_id or self.sucursal_id:
                errores["tipo_alcance"] = (
                    "El alcance global no admite empresa ni sucursal."
                )
        elif self.tipo_alcance == TipoAlcanceRol.EMPRESA:
            if not self.empresa_id:
                errores["empresa"] = "La empresa es obligatoria para este alcance."
            if self.sucursal_id:
                errores["sucursal"] = (
                    "El alcance de empresa no admite una sucursal."
                )
        elif self.tipo_alcance == TipoAlcanceRol.SUCURSAL:
            if not self.empresa_id:
                errores["empresa"] = "La empresa es obligatoria para este alcance."
            if not self.sucursal_id:
                errores["sucursal"] = (
                    "La sucursal es obligatoria para este alcance."
                )

        if self.sucursal_id and self.empresa_id:
            if self.sucursal.empresa_id != self.empresa_id:
                errores["sucursal"] = (
                    "La sucursal debe pertenecer a la empresa del alcance."
                )

        if self.activo and self.revocado_en:
            errores["revocado_en"] = (
                "Un rol activo no puede tener fecha de revocación."
            )
        if not self.activo and not self.revocado_en:
            errores["revocado_en"] = (
                "Un rol inactivo debe conservar su fecha de revocación."
            )

        if errores:
            raise ValidationError(errores)

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.usuario.correo} - {self.rol.codigo}"
