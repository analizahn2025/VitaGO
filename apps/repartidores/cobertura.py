"""Departamento fijo administrado, independiente de la posición GPS actual."""

from django.conf import settings
from rest_framework.exceptions import ValidationError

from apps.geografia.models import Pais
from apps.geografia.normalizacion import clave_departamento, nombre_departamento


def filtrar_cobertura_origen(consulta, origen):
    clave = clave_departamento(origen.nivel_administrativo_1)
    if not clave:
        return consulta.none()
    return consulta.filter(pais_operacion_id=origen.pais_id, departamento_operacion_clave=clave)


def validar_cobertura_solicitud(repartidor, solicitud):
    if not repartidor.cobertura_configurada or not repartidor.pais_operacion.activo:
        raise ValidationError({"repartidor_id": "El administrador debe configurar el país y departamento de operación del motorista."})
    clave = clave_departamento(solicitud.origen.nivel_administrativo_1)
    if not clave:
        raise ValidationError({"origen_id": "La ubicación de recolección no tiene departamento registrado."})
    if repartidor.pais_operacion_id != solicitud.origen.pais_id or repartidor.departamento_operacion_clave != clave:
        raise ValidationError({"repartidor_id": "El motorista no está habilitado para el país y departamento de la recolección."})


def preparar_cobertura(datos, empresa):
    departamento = nombre_departamento(datos.get("departamento_operacion"))
    pais_id = datos.get("pais_operacion_id")
    if not departamento:
        raise ValidationError({"departamento_operacion": "Indique el departamento fijo de operación."})
    if len(clave_departamento(departamento)) > 150:
        raise ValidationError({"departamento_operacion": "El departamento normalizado supera la longitud permitida."})
    if settings.MODO_APLICACION == "CORPORATIVO":
        if empresa is None:
            raise ValidationError({"empresa_id": "La cobertura Corporate requiere un motorista de empresa."})
        if pais_id and pais_id != empresa.pais_id:
            raise ValidationError({"pais_operacion_id": "Debe coincidir con el país de la empresa."})
        pais_id = empresa.pais_id
    if not pais_id:
        raise ValidationError({"pais_operacion_id": "El país de operación es obligatorio en Network."})
    try:
        pais = Pais.objects.get(pk=pais_id, activo=True)
    except Pais.DoesNotExist as error:
        raise ValidationError({"pais_operacion_id": "El país no existe o está inactivo."}) from error
    return {"pais_operacion": pais, "departamento_operacion": departamento,
            "departamento_operacion_clave": clave_departamento(departamento)}


def opciones_departamentos(usuario, filtros):
    from rest_framework.exceptions import PermissionDenied
    from apps.ubicaciones.models import UbicacionEmpresa
    from apps.usuarios.servicios import obtener_alcances_permiso, usuario_tiene_permiso
    from apps.organizaciones.models import Empresa
    consulta = UbicacionEmpresa.objects.filter(estado="APROBADO", permite_origen=True, empresa__estado="ACTIVO",
        ubicacion__estado="ACTIVO", ubicacion__pais__activo=True)
    if settings.MODO_APLICACION == "CORPORATIVO":
        empresa_id = filtros.get("empresa_id")
        if not empresa_id:
            raise ValidationError({"empresa_id": "Indique la empresa para consultar sus departamentos registrados."})
        empresa = Empresa.objects.filter(pk=empresa_id, estado="ACTIVO").first()
        if empresa is None or not usuario_tiene_permiso(usuario, "repartidor.administrar", empresa=empresa):
            raise PermissionDenied('No tiene permiso para configurar la flota de esta empresa.')
        consulta = consulta.filter(empresa=empresa)
    elif filtros.get("empresa_id"):
        raise ValidationError({"empresa_id": "La cobertura Network corresponde a la flota compartida."})
    elif not obtener_alcances_permiso(usuario, "repartidor.administrar").global_:
        raise PermissionDenied('La configuración de flota Network requiere alcance global.')
    if filtros.get("pais_operacion_id"):
        consulta = consulta.filter(ubicacion__pais_id=filtros["pais_operacion_id"])
    resultado = {}
    for pais_id, pais, departamento in consulta.order_by("ubicacion__pais__nombre", "ubicacion__nivel_administrativo_1").values_list(
            "ubicacion__pais_id", "ubicacion__pais__nombre", "ubicacion__nivel_administrativo_1").distinct():
        clave = clave_departamento(departamento)
        if clave:
            resultado.setdefault((pais_id, clave), {"pais_operacion_id": str(pais_id), "pais_nombre": pais,
                                                  "departamento_operacion": nombre_departamento(departamento)})
    return {"departamentos": list(resultado.values())}
