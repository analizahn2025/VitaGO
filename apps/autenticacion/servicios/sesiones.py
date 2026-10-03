"""Ciclo de vida y rotación de sesiones autenticadas."""

import uuid
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.autenticacion.excepciones import (
    SesionNoDisponible,
    TokenRefrescoInvalido,
)
from apps.autenticacion.models import SesionAutenticacion
from apps.autenticacion.opciones import MotivoRevocacionSesion
from apps.autenticacion.servicios.tokens import (
    ParTokens,
    calcular_hash_token_refresco,
    crear_par_tokens,
    validar_token_refresco,
)


@dataclass(frozen=True, slots=True)
class MetadatosSesion:
    identificador_dispositivo: str | None = None
    direccion_ip: str | None = None
    agente_usuario: str | None = None


@dataclass(frozen=True, slots=True)
class ResultadoSesion:
    sesion: SesionAutenticacion
    tokens: ParTokens


def _crear_sesion(usuario, metadatos, familia=None):
    identificador_sesion = uuid.uuid4()
    familia = familia or uuid.uuid4()
    tokens = crear_par_tokens(usuario, identificador_sesion, familia)

    sesion = SesionAutenticacion.objetos.create(
        id=identificador_sesion,
        usuario=usuario,
        hash_token_refresco=calcular_hash_token_refresco(
            tokens.token_refresco
        ),
        identificador_token=tokens.identificador_token_refresco,
        familia=familia,
        identificador_dispositivo=metadatos.identificador_dispositivo,
        direccion_ip=metadatos.direccion_ip,
        agente_usuario=metadatos.agente_usuario,
        expira_en=tokens.expira_token_refresco_en,
    )
    return ResultadoSesion(sesion=sesion, tokens=tokens)


@transaction.atomic
def crear_sesion(usuario, metadatos):
    if not usuario.is_active:
        raise SesionNoDisponible("El usuario no está activo.")
    return _crear_sesion(usuario, metadatos)


def _revocar_sesiones_activas(filtros, motivo, instante):
    return SesionAutenticacion.objetos.filter(
        **filtros,
        revocado_en__isnull=True,
    ).update(
        revocado_en=instante,
        motivo_revocacion=motivo,
        actualizado_en=instante,
    )


def renovar_sesion(token_refresco, metadatos):
    token = validar_token_refresco(token_refresco)
    hash_token = calcular_hash_token_refresco(token_refresco)
    ahora = timezone.now()
    error = None
    resultado = None

    with transaction.atomic():
        try:
            sesion = (
                SesionAutenticacion.objetos.select_for_update()
                .select_related("usuario")
                .get(hash_token_refresco=hash_token)
            )
        except SesionAutenticacion.DoesNotExist as exc:
            raise TokenRefrescoInvalido() from exc

        if sesion.revocado_en is not None:
            _revocar_sesiones_activas(
                {"familia": sesion.familia},
                MotivoRevocacionSesion.REUTILIZACION_TOKEN,
                ahora,
            )
            error = TokenRefrescoInvalido(
                "Se detectó la reutilización de un token de refresco."
            )
        elif sesion.expira_en <= ahora:
            _revocar_sesiones_activas(
                {"id": sesion.id},
                MotivoRevocacionSesion.EXPIRACION,
                ahora,
            )
            error = TokenRefrescoInvalido("La sesión ya expiró.")
        elif not sesion.usuario.is_active:
            _revocar_sesiones_activas(
                {"usuario": sesion.usuario},
                MotivoRevocacionSesion.USUARIO_INACTIVO,
                ahora,
            )
            error = SesionNoDisponible("El usuario no está activo.")
        else:
            claims_coinciden = all(
                (
                    str(token["sesion_id"]) == str(sesion.id),
                    str(token["familia"]) == str(sesion.familia),
                    str(token["usuario_id"]) == str(sesion.usuario_id),
                    str(token["jti"]) == sesion.identificador_token,
                )
            )
            if not claims_coinciden:
                error = TokenRefrescoInvalido(
                    "El token no corresponde a la sesión registrada."
                )
            else:
                metadatos_rotacion = MetadatosSesion(
                    identificador_dispositivo=(
                        metadatos.identificador_dispositivo
                        or sesion.identificador_dispositivo
                    ),
                    direccion_ip=metadatos.direccion_ip or sesion.direccion_ip,
                    agente_usuario=(
                        metadatos.agente_usuario or sesion.agente_usuario
                    ),
                )
                resultado = _crear_sesion(
                    sesion.usuario,
                    metadatos_rotacion,
                    familia=sesion.familia,
                )
                SesionAutenticacion.objetos.filter(id=sesion.id).update(
                    ultimo_uso_en=ahora,
                    revocado_en=ahora,
                    motivo_revocacion=MotivoRevocacionSesion.ROTACION,
                    reemplazada_por=resultado.sesion,
                    actualizado_en=ahora,
                )

    if error:
        raise error
    return resultado


@transaction.atomic
def cerrar_sesion(usuario, identificador_sesion):
    ahora = timezone.now()
    try:
        sesion = SesionAutenticacion.objetos.select_for_update().get(
            id=identificador_sesion,
            usuario=usuario,
        )
    except SesionAutenticacion.DoesNotExist as exc:
        raise SesionNoDisponible() from exc

    if sesion.revocado_en is None:
        SesionAutenticacion.objetos.filter(id=sesion.id).update(
            revocado_en=ahora,
            motivo_revocacion=MotivoRevocacionSesion.CIERRE_SESION,
            actualizado_en=ahora,
        )


@transaction.atomic
def cerrar_todas_las_sesiones(usuario):
    ahora = timezone.now()
    return _revocar_sesiones_activas(
        {"usuario": usuario},
        MotivoRevocacionSesion.CIERRE_TOTAL,
        ahora,
    )


@transaction.atomic
def revocar_sesiones_usuario_inactivo(usuario):
    """Revoca todas las sesiones por suspensión o desactivación administrativa."""
    ahora = timezone.now()
    return _revocar_sesiones_activas(
        {"usuario": usuario},
        MotivoRevocacionSesion.USUARIO_INACTIVO,
        ahora,
    )
