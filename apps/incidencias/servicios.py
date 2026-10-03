"""Casos de uso transaccionales para incidencias operativas."""

import uuid

from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.evidencias.servicios import validar_archivo_imagen
from apps.incidencias.models import (
    EventoIncidencia,
    EvidenciaIncidencia,
    Incidencia,
)
from apps.incidencias.opciones import EstadoIncidencia, TipoEventoIncidencia
from apps.incidencias.selectores import obtener_incidencia_autorizada
from apps.jornadas.models import JornadaRepartidor
from apps.jornadas.opciones import EstadoJornada
from apps.repartidores.models import Repartidor
from apps.solicitudes.models import AsignacionSolicitud, Solicitud
from apps.usuarios.opciones import EstadoUsuario
from apps.usuarios.servicios import usuario_tiene_permiso


TRANSICIONES_REVISION = {
    EstadoIncidencia.ABIERTA: {
        EstadoIncidencia.EN_REVISION,
        EstadoIncidencia.CERRADA,
    },
    EstadoIncidencia.EN_REVISION: {EstadoIncidencia.CERRADA},
}


def _obtener_repartidor_propio_bloqueado(usuario):
    try:
        return (
            Repartidor.objects.select_for_update(of=("self",))
            .select_related("empresa")
            .get(
                usuario=usuario,
                activo=True,
                usuario__estado=EstadoUsuario.ACTIVO,
            )
        )
    except Repartidor.DoesNotExist as error:
        raise Http404(
            "El usuario no posee un perfil activo de motorista."
        ) from error


def _obtener_jornada_activa_bloqueada(repartidor):
    try:
        return JornadaRepartidor.objects.select_for_update(of=("self",)).get(
            repartidor=repartidor,
            estado=EstadoJornada.ACTIVA,
        )
    except JornadaRepartidor.DoesNotExist as error:
        raise ValidationError(
            {"jornada": "Debe tener una jornada activa para reportar."}
        ) from error


def _obtener_solicitud_relacionada(repartidor, solicitud_id, reportada_en):
    if solicitud_id is None:
        return None
    try:
        solicitud = Solicitud.objects.get(id=solicitud_id)
    except (Solicitud.DoesNotExist, ValueError) as error:
        raise Http404("La solicitud relacionada no existe.") from error

    asignada = (
        AsignacionSolicitud.objects.filter(
            solicitud=solicitud,
            repartidor=repartidor,
            asignada_en__lte=reportada_en,
        )
        .filter(
            Q(finalizada_en__isnull=True)
            | Q(finalizada_en__gte=reportada_en)
        )
        .exists()
    )
    if not asignada:
        raise ValidationError(
            {
                "solicitud_id": (
                    "La solicitud no pertenecía al motorista en el momento "
                    "reportado."
                )
            }
        )
    return solicitud


@transaction.atomic
def crear_incidencia(usuario, datos_validados):
    repartidor = _obtener_repartidor_propio_bloqueado(usuario)
    if not usuario_tiene_permiso(
        usuario,
        "incidencia.crear",
        empresa=repartidor.empresa,
    ):
        raise PermissionDenied(
            'No tiene el permiso requerido: "incidencia.crear".'
        )
    jornada = _obtener_jornada_activa_bloqueada(repartidor)
    reportada_en = datos_validados["reportada_en"]
    if not jornada.iniciada_en <= reportada_en <= timezone.now():
        raise ValidationError(
            {
                "reportada_en": (
                    "Debe pertenecer al intervalo transcurrido de la jornada."
                )
            }
        )
    solicitud = _obtener_solicitud_relacionada(
        repartidor,
        datos_validados.get("solicitud_id"),
        reportada_en,
    )
    incidencia = Incidencia.objects.create(
        jornada=jornada,
        repartidor=repartidor,
        solicitud=solicitud,
        descripcion=datos_validados["descripcion"],
        latitud=datos_validados.get("latitud"),
        longitud=datos_validados.get("longitud"),
        reportada_en=reportada_en,
    )
    EventoIncidencia.objects.create(
        incidencia=incidencia,
        tipo=TipoEventoIncidencia.REPORTADA,
        realizado_por=usuario,
        estado_nuevo=EstadoIncidencia.ABIERTA,
    )
    return incidencia


@transaction.atomic
def revisar_incidencia(usuario, incidencia_id, datos_validados):
    autorizada = obtener_incidencia_autorizada(usuario, incidencia_id)
    incidencia = (
        Incidencia.objects.select_for_update(of=("self",))
        .select_related("repartidor", "repartidor__empresa")
        .get(id=autorizada.id)
    )
    if not usuario_tiene_permiso(
        usuario,
        "incidencia.revisar",
        empresa=incidencia.repartidor.empresa,
    ):
        raise PermissionDenied(
            'No tiene el permiso requerido: "incidencia.revisar".'
        )

    estado_nuevo = datos_validados["estado"]
    if estado_nuevo not in TRANSICIONES_REVISION.get(incidencia.estado, set()):
        raise ValidationError(
            {
                "estado": (
                    f"No se permite cambiar de {incidencia.estado} a "
                    f"{estado_nuevo}."
                )
            }
        )
    ahora = timezone.now()
    estado_anterior = incidencia.estado
    incidencia.estado = estado_nuevo
    incidencia.revisada_por = usuario
    incidencia.revisada_en = ahora
    campos = [
        "estado",
        "revisada_por",
        "revisada_en",
        "actualizado_en",
    ]
    if estado_nuevo == EstadoIncidencia.CERRADA:
        incidencia.cerrada_en = ahora
        campos.append("cerrada_en")
    incidencia.save(update_fields=campos)
    EventoIncidencia.objects.create(
        incidencia=incidencia,
        tipo=(
            TipoEventoIncidencia.CERRADA
            if estado_nuevo == EstadoIncidencia.CERRADA
            else TipoEventoIncidencia.EN_REVISION
        ),
        realizado_por=usuario,
        estado_anterior=estado_anterior,
        estado_nuevo=estado_nuevo,
        notas=datos_validados.get("notas"),
    )
    return incidencia


def _validar_propiedad_evidencia(usuario, incidencia):
    if incidencia.repartidor.usuario_id != usuario.pk:
        raise PermissionDenied(
            "Solo el motorista que reportó la incidencia puede agregar evidencia."
        )
    if incidencia.estado == EstadoIncidencia.CERRADA:
        raise ValidationError(
            {"incidencia": "No puede agregar evidencia a una incidencia cerrada."}
        )
    if not usuario_tiene_permiso(
        usuario,
        "evidencia.crear",
        empresa=incidencia.repartidor.empresa,
    ):
        raise PermissionDenied(
            'No tiene el permiso requerido: "evidencia.crear".'
        )


def _validar_fecha_evidencia(incidencia, capturada_en):
    limite_superior = incidencia.jornada.finalizada_en or timezone.now()
    if not incidencia.jornada.iniciada_en <= capturada_en <= limite_superior:
        raise ValidationError(
            {
                "capturada_en": (
                    "Debe pertenecer al intervalo de la jornada de la incidencia."
                )
            }
        )


def registrar_evidencia_incidencia(usuario, incidencia_id, datos_validados):
    datos = dict(datos_validados)
    archivo = datos.pop("archivo")
    tipo_contenido, extension = validar_archivo_imagen(archivo)
    clave_guardada = None

    try:
        with transaction.atomic():
            autorizada = obtener_incidencia_autorizada(usuario, incidencia_id)
            incidencia = (
                Incidencia.objects.select_for_update(of=("self",))
                .select_related(
                    "jornada",
                    "repartidor",
                    "repartidor__empresa",
                )
                .get(id=autorizada.id)
            )
            _validar_propiedad_evidencia(usuario, incidencia)
            _validar_fecha_evidencia(incidencia, datos["capturada_en"])

            clave_propuesta = (
                f"incidencias/{incidencia.id}/{uuid.uuid4().hex}.{extension}"
            )
            archivo.seek(0)
            clave_guardada = default_storage.save(clave_propuesta, archivo)
            evidencia = EvidenciaIncidencia.objects.create(
                incidencia=incidencia,
                repartidor=incidencia.repartidor,
                clave_almacenamiento=clave_guardada,
                tipo_contenido=tipo_contenido,
                tamano_bytes=archivo.size,
                **datos,
            )
            EventoIncidencia.objects.create(
                incidencia=incidencia,
                tipo=TipoEventoIncidencia.EVIDENCIA_REGISTRADA,
                realizado_por=usuario,
                metadatos={
                    "evidencia_id": str(evidencia.id),
                    "capturada_en": evidencia.capturada_en.isoformat(),
                },
            )
            return evidencia
    except Exception:
        if clave_guardada and default_storage.exists(clave_guardada):
            default_storage.delete(clave_guardada)
        raise

