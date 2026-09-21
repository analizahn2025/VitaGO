from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def verificar_salud(solicitud):
    """Informa la salud del proceso sin revelar detalles internos."""
    return Response(
        {
            "estado": "correcto",
            "servicio": settings.NOMBRE_APLICACION,
        }
    )
