"""Paginación HTTP compartida con nombres del contrato en español."""

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class PaginacionEstandar(PageNumberPagination):
    page_size = 20
    page_query_param = "pagina"
    page_size_query_param = "tamano_pagina"
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response(
            {
                "conteo": self.page.paginator.count,
                "pagina_siguiente": self.get_next_link(),
                "pagina_anterior": self.get_previous_link(),
                "resultados": data,
            }
        )
