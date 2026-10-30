from rest_framework.exceptions import APIException


class CreacionSolicitudNoDisponible(APIException):
    status_code = 409
    default_detail = (
        "La creación de solicitudes en VitaGo Network estará disponible "
        "cuando la cotización de ruta y tarifa pueda calcularse en el backend."
    )
    default_code = "cotizacion_no_disponible"


class LimiteSolicitudesRepartidor(APIException):
    status_code = 409
    default_code = "limite_solicitudes_repartidor"

    def __init__(self, limite=5):
        super().__init__(
            detail={
                "repartidor_id": [
                    f"El motorista alcanzó el límite de {limite} solicitudes activas."
                ]
            }
        )


class CupoRecipientesInsuficiente(APIException):
    status_code = 409
    default_code = "cupo_recipientes_insuficiente"

    def __init__(self, mensaje):
        super().__init__({"repartidor_id": [mensaje]})
