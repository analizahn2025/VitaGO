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

    def __init__(self):
        super().__init__(
            detail={
                "repartidor_id": [
                    "El motorista ya tiene cinco solicitudes activas."
                ]
            }
        )
