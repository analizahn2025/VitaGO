"""Casos de uso para registrar evidencias operativas privadas."""

import uuid

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import transaction
from django.http import Http404
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.evidencias.models import EvidenciaSolicitud
from apps.evidencias.opciones import TipoEvidenciaSolicitud
from apps.repartidores.models import Repartidor
from apps.solicitudes.models import EventoSolicitud, Solicitud
from apps.solicitudes.opciones import EstadoSolicitud, TipoEventoSolicitud
from apps.usuarios.servicios import usuario_tiene_permiso


TIPOS_CONTENIDO_PERMITIDOS = {
    "image/jpeg": ("jpg", lambda cabecera: cabecera.startswith(b"\xff\xd8\xff")),
    "image/png": ("png", lambda cabecera: cabecera.startswith(b"\x89PNG\r\n\x1a\n")),
    "image/webp": (
        "webp",
        lambda cabecera: (
            len(cabecera) >= 12
            and cabecera[:4] == b"RIFF"
            and cabecera[8:12] == b"WEBP"
        ),
    ),
}

ESTADOS_POR_TIPO_EVIDENCIA = {
    TipoEvidenciaSolicitud.FOTO_RECOLECCION: {EstadoSolicitud.EN_RECOLECCION},
    TipoEvidenciaSolicitud.FOTO_ENTREGA: {EstadoSolicitud.EN_DESTINO},
    TipoEvidenciaSolicitud.FOTO_INCIDENCIA: {
        EstadoSolicitud.ASIGNADA,
        EstadoSolicitud.HACIA_RECOLECCION,
        EstadoSolicitud.EN_RECOLECCION,
        EstadoSolicitud.RECOLECTADA,
        EstadoSolicitud.EN_TRANSITO,
        EstadoSolicitud.EN_DESTINO,
    },
}


def validar_archivo_imagen(archivo):
    tipo_contenido = (getattr(archivo, "content_type", "") or "").lower()
    configuracion_tipo = TIPOS_CONTENIDO_PERMITIDOS.get(tipo_contenido)
    if configuracion_tipo is None:
        raise ValidationError(
            {"archivo": "El archivo debe ser una imagen JPEG, PNG o WebP."}
        )

    maximo_bytes = settings.TAMANO_MAXIMO_EVIDENCIA_MB * 1024 * 1024
    if archivo.size > maximo_bytes:
        raise ValidationError(
            {
                "archivo": (
                    "La imagen supera el tamaño máximo permitido de "
                    f"{settings.TAMANO_MAXIMO_EVIDENCIA_MB} MB."
                )
            }
        )

    posicion_inicial = archivo.tell()
    cabecera = archivo.read(16)
    archivo.seek(posicion_inicial)
    extension, firma_valida = configuracion_tipo
    if not firma_valida(cabecera):
        raise ValidationError(
            {"archivo": "El contenido del archivo no coincide con una imagen válida."}
        )
    return tipo_contenido, extension


def _validar_repartidor_asignado(usuario, solicitud):
    if solicitud.repartidor_asignado_id is None:
        raise ValidationError(
            {"solicitud": "La solicitud no tiene un motorista asignado."}
        )
    try:
        repartidor = Repartidor.objects.select_for_update(of=("self",)).get(
            id=solicitud.repartidor_asignado_id,
            activo=True,
        )
    except Repartidor.DoesNotExist as error:
        raise ValidationError(
            {"solicitud": "El motorista asignado no posee un perfil activo."}
        ) from error
    if repartidor.usuario_id != usuario.pk:
        raise PermissionDenied(
            "Solo el motorista asignado puede registrar evidencias."
        )
    if not usuario_tiene_permiso(
        usuario,
        "evidencia.crear",
        empresa=solicitud.empresa,
        sucursal=solicitud.sucursal,
    ):
        raise PermissionDenied(
            'No tiene el permiso requerido: "evidencia.crear".'
        )
    return repartidor


def registrar_evidencia(usuario, solicitud_id, datos_validados):
    datos = dict(datos_validados)
    archivo = datos.pop("archivo")
    tipo_contenido, extension = validar_archivo_imagen(archivo)
    clave_guardada = None

    try:
        with transaction.atomic():
            try:
                solicitud = (
                    Solicitud.objects.select_for_update(of=("self",))
                    .select_related("empresa", "sucursal")
                    .get(id=solicitud_id)
                )
            except (Solicitud.DoesNotExist, ValueError) as error:
                raise Http404("La solicitud no existe.") from error

            repartidor = _validar_repartidor_asignado(usuario, solicitud)
            tipo = datos["tipo"]
            if solicitud.estado not in ESTADOS_POR_TIPO_EVIDENCIA[tipo]:
                raise ValidationError(
                    {
                        "tipo": (
                            "Este tipo de evidencia no puede registrarse en el "
                            f"estado {solicitud.estado}."
                        )
                    }
                )

            clave_propuesta = (
                f"evidencias/{solicitud.id}/{uuid.uuid4().hex}.{extension}"
            )
            archivo.seek(0)
            clave_guardada = default_storage.save(clave_propuesta, archivo)
            evidencia = EvidenciaSolicitud.objects.create(
                solicitud=solicitud,
                repartidor=repartidor,
                clave_almacenamiento=clave_guardada,
                tipo_contenido=tipo_contenido,
                tamano_bytes=archivo.size,
                **datos,
            )
            EventoSolicitud.objects.create(
                solicitud=solicitud,
                tipo=TipoEventoSolicitud.EVIDENCIA_REGISTRADA,
                realizado_por=usuario,
                repartidor=repartidor,
                latitud=evidencia.latitud,
                longitud=evidencia.longitud,
                metadatos={
                    "evidencia_id": str(evidencia.id),
                    "tipo_evidencia": evidencia.tipo,
                    "capturada_en": evidencia.capturada_en.isoformat(),
                },
            )
            return evidencia
    except Exception:
        if clave_guardada and default_storage.exists(clave_guardada):
            default_storage.delete(clave_guardada)
        raise
