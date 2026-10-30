"""Configuración compartida: por empresa en Corporate y general en Network."""

from django.conf import settings
from django.db import transaction
from django.db.models import F, IntegerField, Subquery, Value
from django.db.models.functions import Coalesce

from apps.organizaciones.models import Empresa, LimitesMotoristasRed


LIMITES_PREDETERMINADOS = {"limite_tubos": 20, "limite_frascos": 20, "limite_solicitudes": 5}
CAMPOS_LIMITES = {clave: clave + "_por_motorista" for clave in LIMITES_PREDETERMINADOS}


def limites_de_configuracion(configuracion):
    return {clave: getattr(configuracion, campo) for clave, campo in CAMPOS_LIMITES.items()}


def obtener_configuracion_red(*, bloquear=False):
    if bloquear:
        if not transaction.get_connection().in_atomic_block:
            raise RuntimeError("Modificar o validar cupos requiere una transacción.")
        return LimitesMotoristasRed.objects.select_for_update(no_key=True).get_or_create(pk=1)[0]
    # GET no crea filas. La migración inicializa la configuración de la red.
    return LimitesMotoristasRed.objects.filter(pk=1).first() or LimitesMotoristasRed(pk=1)


def obtener_limites_repartidor(repartidor, *, bloquear=False):
    if not bloquear and all(hasattr(repartidor, clave + "_efectivo") for clave in CAMPOS_LIMITES):
        return {clave: getattr(repartidor, clave + "_efectivo") for clave in CAMPOS_LIMITES}
    if settings.MODO_APLICACION == "EXTERNO":
        if bloquear:
            return _leer_limites_bloqueados(LimitesMotoristasRed, 1)
        return limites_de_configuracion(obtener_configuracion_red())
    if repartidor.empresa_id is None:
        return dict(LIMITES_PREDETERMINADOS)
    if bloquear:
        return _leer_limites_bloqueados(Empresa, repartidor.empresa_id)
    return limites_de_configuracion(Empresa.objects.only(*CAMPOS_LIMITES.values()).get(pk=repartidor.empresa_id))


def _leer_limites_bloqueados(modelo, identificador):
    conexion = transaction.get_connection()
    if not conexion.in_atomic_block:
        raise RuntimeError("Validar cupos requiere una transacción.")
    if conexion.vendor == "postgresql":
        # Lectores compatibles entre sí: asignar a dos motoristas distintos no
        # serializa toda la empresa/red. FOR SHARE impide cambiar los límites
        # hasta confirmar la asignación. El escritor usa FOR NO KEY UPDATE.
        citar = conexion.ops.quote_name
        campos = ", ".join(citar(campo) for campo in CAMPOS_LIMITES.values())
        with conexion.cursor() as cursor:
            cursor.execute(
                f"SELECT {campos} FROM {citar(modelo._meta.db_table)} WHERE id = %s FOR SHARE",
                [identificador],
            )
            fila = cursor.fetchone()
        if fila is None:
            raise modelo.DoesNotExist("No existe la configuración de límites.")
        return dict(zip(CAMPOS_LIMITES, fila))
    return limites_de_configuracion(modelo.objects.select_for_update().get(pk=identificador))


def anotar_limites_repartidores(consulta):
    expresiones = {}
    for clave, campo in CAMPOS_LIMITES.items():
        if settings.MODO_APLICACION == "EXTERNO":
            expresion = Subquery(LimitesMotoristasRed.objects.filter(pk=1).values(campo)[:1])
        else:
            expresion = F("empresa__" + campo)
        expresiones[clave + "_efectivo"] = Coalesce(
            expresion, Value(LIMITES_PREDETERMINADOS[clave]), output_field=IntegerField(),
        )
    return consulta.annotate(**expresiones)
