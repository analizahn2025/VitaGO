"""Persistencia de sesiones revocables para VitaGo Network."""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.autenticacion.opciones import MotivoRevocacionSesion
from apps.nucleo.models import ModeloUUIDConMarcasDeTiempo


class SesionAutenticacion(ModeloUUIDConMarcasDeTiempo):
    usuario = models.ForeignKey(
        "usuarios.Usuario",
        on_delete=models.PROTECT,
        related_name="sesiones_autenticacion",
    )
    hash_token_refresco = models.CharField(max_length=64, unique=True)
    identificador_token = models.CharField(max_length=64, unique=True)
    familia = models.UUIDField()
    identificador_dispositivo = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )
    direccion_ip = models.GenericIPAddressField(
        protocol="both",
        unpack_ipv4=True,
        null=True,
        blank=True,
    )
    agente_usuario = models.TextField(null=True, blank=True)
    expira_en = models.DateTimeField()
    ultimo_uso_en = models.DateTimeField(null=True, blank=True)
    revocado_en = models.DateTimeField(null=True, blank=True)
    motivo_revocacion = models.CharField(
        max_length=80,
        choices=MotivoRevocacionSesion.choices,
        null=True,
        blank=True,
    )
    reemplazada_por = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="sesiones_reemplazadas",
        null=True,
        blank=True,
    )

    objetos = models.Manager()

    class Meta:
        db_table = "sesiones_autenticacion"
        ordering = ("-creado_en",)
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        revocado_en__isnull=True,
                        motivo_revocacion__isnull=True,
                        reemplazada_por__isnull=True,
                    )
                    | models.Q(
                        revocado_en__isnull=False,
                        motivo_revocacion__isnull=False,
                    )
                ),
                name="ses_auth_revocacion_valida_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=("usuario", "revocado_en"),
                name="ses_auth_usr_rev_idx",
            ),
            models.Index(
                fields=("familia", "revocado_en"),
                name="ses_auth_fam_rev_idx",
            ),
            models.Index(
                fields=("expira_en",),
                name="ses_auth_expira_idx",
            ),
            models.Index(
                fields=("identificador_dispositivo",),
                name="ses_auth_dispositivo_idx",
            ),
        ]
        verbose_name = "sesión de autenticación"
        verbose_name_plural = "sesiones de autenticación"

    @property
    def esta_activa(self):
        return self.revocado_en is None and self.expira_en > timezone.now()

    def clean(self):
        super().clean()
        errores = {}

        if len(self.hash_token_refresco or "") != 64:
            errores["hash_token_refresco"] = (
                "El hash del token de refresco debe contener 64 caracteres."
            )

        if self.revocado_en is None:
            if self.motivo_revocacion:
                errores["motivo_revocacion"] = (
                    "Una sesión activa no puede tener motivo de revocación."
                )
            if self.reemplazada_por_id:
                errores["reemplazada_por"] = (
                    "Una sesión activa no puede haber sido reemplazada."
                )
        elif not self.motivo_revocacion:
            errores["motivo_revocacion"] = (
                "Una sesión revocada debe conservar el motivo."
            )

        if self.reemplazada_por_id == self.id:
            errores["reemplazada_por"] = (
                "Una sesión no puede reemplazarse a sí misma."
            )

        if errores:
            raise ValidationError(errores)

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.usuario.correo} - {self.identificador_token}"
