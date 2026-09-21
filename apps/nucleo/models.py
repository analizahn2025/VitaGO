"""Modelos abstractos reutilizables de los dominios de VitaGo."""

import uuid

from django.db import models


class ModeloUUID(models.Model):
    """Modelo abstracto con una llave primaria UUID no editable."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class ModeloConMarcasDeTiempo(models.Model):
    """Modelo abstracto con fechas de creación y modificación."""

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ModeloUUIDConMarcasDeTiempo(ModeloUUID, ModeloConMarcasDeTiempo):
    """Base para entidades con UUID y marcas de tiempo."""

    class Meta:
        abstract = True
