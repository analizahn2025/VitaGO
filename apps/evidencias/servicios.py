"""Casos de uso para registrar evidencias operativas privadas."""

import logging
import uuid
import warnings
from io import BytesIO

from PIL import Image

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import transaction
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.evidencias.models import EvidenciaSolicitud
from apps.evidencias.opciones import TipoEvidenciaSolicitud
from apps.repartidores.models import Repartidor
from apps.solicitudes.models import EventoSolicitud, Solicitud
from apps.solicitudes.opciones import EstadoSolicitud, TipoEventoSolicitud
from apps.usuarios.servicios import usuario_tiene_permiso


registro = logging.getLogger("vitago.api")


TIPOS_CONTENIDO_PERMITIDOS = {
    "image/jpeg": ("jpg", "JPEG"),
    "image/png": ("png", "PNG"),
    "image/webp": ("webp", "WEBP"),
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
    try:
        archivo.seek(0)
        contenido = archivo.read(maximo_bytes + 1)
    finally:
        archivo.seek(posicion_inicial)
    if len(contenido) > maximo_bytes:
        raise ValidationError({"archivo": "La imagen supera el tamaño máximo permitido."})

    extension, formato_esperado = configuracion_tipo
    formatos_permitidos = tuple(tipo[1] for tipo in TIPOS_CONTENIDO_PERMITIDOS.values())
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(contenido), formats=formatos_permitidos) as imagen:
                if imagen.format != formato_esperado:
                    raise ValidationError({"archivo": "El formato real de la imagen no coincide con su tipo de contenido."})
                if imagen.width * imagen.height > settings.PIXELES_MAXIMOS_EVIDENCIA:
                    raise ValidationError({"archivo": "La imagen supera el máximo permitido de píxeles."})
                if getattr(imagen, "n_frames", 1) != 1:
                    raise ValidationError({"archivo": "La evidencia debe ser una fotografía estática, no una animación."})
                imagen.verify()
            # verify() no decodifica todos los píxeles. Reabrir y cargar para
            # detectar también archivos truncados; no modificar el original.
            with Image.open(BytesIO(contenido), formats=formatos_permitidos) as imagen:
                imagen.load()
    except (OSError, SyntaxError, ValueError, OverflowError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValidationError(
            {"archivo": "La imagen está dañada, incompleta o no es una fotografía válida."}
        ) from error
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


def limpiar_archivo_nuevo(clave):
    """Compensación del archivo recién creado; no sustituye el error original."""
    if clave:
        try:
            default_storage.delete(clave)
        except Exception:
            registro.exception("No se pudo limpiar el archivo nuevo tras un fallo: %s", clave)


def registrar_evidencia(usuario, solicitud_id, datos_validados):
    datos = dict(datos_validados)
    archivo = datos.pop("archivo")
    tipo_contenido, extension = validar_archivo_imagen(archivo)
    clave_guardada = None

    try:
        with transaction.atomic():
            try:
                solicitud = (
                    Solicitud.objects.select_for_update(of=("self",), no_key=True)
                    .select_related("empresa", "sucursal")
                    .get(id=solicitud_id)
                )
            except (Solicitud.DoesNotExist, ValueError) as error:
                raise Http404("La solicitud no existe.") from error

            repartidor = _validar_repartidor_asignado(usuario, solicitud)
            from apps.solicitudes.vigencia import exigir_vigencia_solicitud
            exigir_vigencia_solicitud(solicitud)
            tipo = datos["tipo"]
            if "fuente_temperatura" in datos:
                raise ValidationError({"fuente_temperatura": "La fuente la determina el servidor."})
            if tipo == TipoEvidenciaSolicitud.FOTO_RECOLECCION:
                from apps.evidencias.temperaturas import validar_temperatura
                datos["temperatura_contenedor_c"] = validar_temperatura(datos.get("temperatura_contenedor_c"))
                datos["fuente_temperatura"] = "MANUAL"
                from apps.solicitudes.servicios import validar_cantidad_tubos
                validar_cantidad_tubos(solicitud.cantidad_tubos)
            elif "temperatura_contenedor_c" in datos:
                raise ValidationError({"temperatura_contenedor_c": "Solo corresponde a la recolección."})
            if solicitud.estado not in ESTADOS_POR_TIPO_EVIDENCIA[tipo]:
                raise ValidationError(
                    {
                        "tipo": (
                            "Este tipo de evidencia no puede registrarse en el "
                            f"estado {solicitud.estado}."
                        )
                    }
                )

            es_cierre_etapa = tipo in {
                TipoEvidenciaSolicitud.FOTO_RECOLECCION, TipoEvidenciaSolicitud.FOTO_ENTREGA,
            }
            if es_cierre_etapa:
                from apps.solicitudes.flujo_automatico import exigir_siguiente_parada
                tipo_parada = ("RECOLECCION" if tipo == TipoEvidenciaSolicitud.FOTO_RECOLECCION
                               else "ENVIO_ESPECIAL" if solicitud.modalidad == "ESPECIAL" else "ENTREGA")
                exigir_siguiente_parada(solicitud, repartidor, tipo_parada)
                if (tipo == TipoEvidenciaSolicitud.FOTO_RECOLECCION
                        and solicitud.modalidad == "ESPECIAL"
                        and repartidor.estado_operativo not in ("AVAILABLE", "ON_ROUTE")):
                    raise ValidationError({"estado_operativo": "Reanude la operación antes de iniciar un envío especial."})

            # Hora oficial de registro, nunca la fecha manipulable del dispositivo.
            datos["capturada_en"] = timezone.now()
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
                    "temperatura_contenedor_c": str(evidencia.temperatura_contenedor_c) if evidencia.temperatura_contenedor_c is not None else None,
                    "fuente_temperatura": evidencia.fuente_temperatura,
                    "capturada_en": evidencia.capturada_en.isoformat(),
                },
            )
            if es_cierre_etapa:
                from apps.solicitudes.servicios import cambiar_estado_solicitud
                datos_transicion = {"latitud": evidencia.latitud, "longitud": evidencia.longitud}
                def avanzar(estado):
                    evidencia.solicitud = cambiar_estado_solicitud(usuario, solicitud.pk, {
                        **datos_transicion, "estado_destino": estado,
                    }, automatismo={"fuente": "EVIDENCIA", "evidencia_id": str(evidencia.pk)})

                if tipo == TipoEvidenciaSolicitud.FOTO_RECOLECCION:
                    avanzar(EstadoSolicitud.RECOLECTADA)
                    from apps.rutas.selectores import obtener_paradas_operativas
                    paradas = obtener_paradas_operativas(repartidor)
                    if paradas and paradas[0]["solicitud_id"] == solicitud.pk:
                        avanzar(EstadoSolicitud.EN_TRANSITO)
                else:
                    avanzar(EstadoSolicitud.ENTREGADA)
            return evidencia
    except Exception:
        limpiar_archivo_nuevo(clave_guardada)
        raise
