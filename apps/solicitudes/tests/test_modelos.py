import uuid

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from apps.solicitudes.models import Solicitud, TipoServicio


class PruebasModelosSolicitudes(SimpleTestCase):
    def test_tipo_servicio_normaliza_codigo(self):
        tipo = TipoServicio(
            codigo=" muestra_biologica ",
            nombre="Muestra biológica",
        )

        tipo.clean()

        self.assertEqual(tipo.codigo, "MUESTRA_BIOLOGICA")

    def test_solicitud_rechaza_sucursal_de_otra_empresa(self):
        empresa_id = uuid.uuid4()
        solicitud = Solicitud(
            empresa_id=empresa_id,
            sucursal_id=uuid.uuid4(),
        )
        solicitud._state.fields_cache["sucursal"] = type(
            "SucursalTemporal",
            (),
            {"empresa_id": uuid.uuid4()},
        )()

        with self.assertRaises(ValidationError):
            solicitud.clean()
