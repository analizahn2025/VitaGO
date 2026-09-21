from django.db import models

from apps.nucleo.models import ModeloUUIDConMarcasDeTiempo


class Pais(ModeloUUIDConMarcasDeTiempo):
    iso2 = models.CharField(max_length=2, unique=True)
    iso3 = models.CharField(max_length=3)
    nombre = models.CharField(max_length=150)
    codigo_telefonico = models.CharField(max_length=10)
    codigo_moneda = models.CharField(max_length=3)
    zona_horaria_predeterminada = models.CharField(max_length=64)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "paises"
        ordering = ("nombre",)
        indexes = [
            models.Index(fields=("activo",), name="paises_activo_idx"),
        ]
        verbose_name = "país"
        verbose_name_plural = "países"

    def clean(self):
        super().clean()
        self.iso2 = self.iso2.strip().upper()
        self.iso3 = self.iso3.strip().upper()
        self.codigo_moneda = self.codigo_moneda.strip().upper()
        self.codigo_telefonico = self.codigo_telefonico.strip()
        self.zona_horaria_predeterminada = (
            self.zona_horaria_predeterminada.strip()
        )

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nombre} ({self.iso2})"
