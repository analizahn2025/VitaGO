from django.conf import settings
from django.db import connection, DatabaseError
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


@api_view(["GET"])
@permission_classes([AllowAny])
def verificar_disponibilidad(solicitud):
    disponible = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            disponible = cursor.fetchone()[0] == 1
    except DatabaseError:
        pass
    respuesta = Response(
        {"estado": "correcto" if disponible else "no_disponible", "servicio": settings.NOMBRE_APLICACION},
        status=200 if disponible else 503,
    )
    respuesta["Cache-Control"] = "no-store"
    return respuesta
