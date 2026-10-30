from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_201_CREATED
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError
from django.utils import timezone

from apps.nucleo.paginacion import PaginacionEstandar
from apps.repartidores.selectores import (
    listar_repartidores_autorizados,
    listar_repartidores_disponibles,
    obtener_repartidor_autorizado,
    obtener_repartidor_propio,
)
from apps.repartidores.serializadores import (
    SerializadorActualizacionOperacionRepartidor,
    SerializadorConsultaRepartidores,
    SerializadorCreacionRepartidor,
    SerializadorRepartidor,
    SerializadorConsultaResumenMotoristas,
    SerializadorResumenMotorista,
    SerializadorLecturaTemperaturaResumen,
)
from apps.repartidores.servicios import (
    actualizar_operacion_repartidor,
    crear_repartidor,
)
from apps.repartidores.resumenes import (
    construir_resumenes, lecturas_temperatura, listar_motoristas_para_resumen,
    obtener_motorista_para_resumen, periodo_operativo,
)


def _filtros_resumen(request):
    entrada = SerializadorConsultaResumenMotoristas(data=request.query_params.dict())
    entrada.is_valid(raise_exception=True)
    return entrada.validated_data


class VistaResumenesMotoristas(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        filtros = _filtros_resumen(request)
        consulta = listar_motoristas_para_resumen(request.user, filtros)
        paginacion = PaginacionEstandar()
        pagina = paginacion.paginate_queryset(consulta, request, view=self)
        datos = construir_resumenes(pagina, filtros.get("fecha_operativa"))
        return paginacion.get_paginated_response(SerializadorResumenMotorista(datos, many=True).data)


class VistaResumenMotorista(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, repartidor_id):
        filtros = _filtros_resumen(request)
        repartidor = obtener_motorista_para_resumen(request.user, repartidor_id, filtros)
        datos = construir_resumenes([repartidor], filtros.get("fecha_operativa"))[0]
        return Response(SerializadorResumenMotorista(datos).data)


class VistaTemperaturasMotorista(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, repartidor_id):
        filtros = _filtros_resumen(request)
        repartidor = obtener_motorista_para_resumen(request.user, repartidor_id, filtros)
        _, _, inicio, fin = periodo_operativo(repartidor, filtros.get("fecha_operativa"), timezone.now())
        consulta = lecturas_temperatura([repartidor.pk], inicio, fin).select_related("solicitud")
        paginacion = PaginacionEstandar()
        pagina = paginacion.paginate_queryset(consulta, request, view=self)
        return paginacion.get_paginated_response(SerializadorLecturaTemperaturaResumen(pagina, many=True).data)


def _respuesta_paginada(request, vista, consulta):
    paginacion = PaginacionEstandar()
    pagina = paginacion.paginate_queryset(consulta, request, view=vista)
    return paginacion.get_paginated_response(
        SerializadorRepartidor(pagina, many=True).data
    )


class VistaListaCreacionRepartidores(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        entrada = SerializadorConsultaRepartidores(data=request.query_params.dict())
        entrada.is_valid(raise_exception=True)
        consulta = listar_repartidores_autorizados(
            request.user, entrada.validated_data
        )
        return _respuesta_paginada(request, self, consulta)

    def post(self, request):
        entrada = SerializadorCreacionRepartidor(data=request.data)
        entrada.is_valid(raise_exception=True)
        repartidor = crear_repartidor(request.user, entrada.validated_data)
        return Response(
            SerializadorRepartidor(repartidor).data,
            status=HTTP_201_CREATED,
        )


class VistaRepartidoresDisponibles(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        entrada = SerializadorConsultaRepartidores(data=request.query_params.dict())
        entrada.is_valid(raise_exception=True)
        consulta = listar_repartidores_disponibles(
            request.user, entrada.validated_data
        )
        return _respuesta_paginada(request, self, consulta)


class VistaMiPerfilRepartidor(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        repartidor = obtener_repartidor_propio(request.user)
        return Response(
            SerializadorRepartidor(repartidor).data,
            status=HTTP_200_OK,
        )


class VistaDetalleRepartidor(APIView):
    permission_classes = (IsAuthenticated,)

    def patch(self, request, repartidor_id):
        obtener_repartidor_autorizado(request.user, repartidor_id)
        campos = {campo for campo in request.data if campo in {"limite_tubos", "limite_frascos", "limite_solicitudes"}}
        raise ValidationError({
            campo: "Los límites se configuran por empresa en Corporate y para toda la red en Network."
            for campo in campos or {"detail"}
        })

    def get(self, request, repartidor_id):
        repartidor = obtener_repartidor_autorizado(request.user, repartidor_id)
        return Response(
            SerializadorRepartidor(repartidor).data,
            status=HTTP_200_OK,
        )


class VistaOperacionRepartidor(APIView):
    permission_classes = (IsAuthenticated,)

    def patch(self, request, repartidor_id):
        entrada = SerializadorActualizacionOperacionRepartidor(data=request.data)
        entrada.is_valid(raise_exception=True)
        repartidor = actualizar_operacion_repartidor(
            request.user,
            repartidor_id,
            entrada.validated_data,
        )
        return Response(
            SerializadorRepartidor(repartidor).data,
            status=HTTP_200_OK,
        )
