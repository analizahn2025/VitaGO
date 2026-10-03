from django.db import migrations


CODIGO = "EMPRESA_TRANSPORTE"


def agregar_tipo_empresa_transporte(aplicaciones, editor_esquema):
    TipoUbicacion = aplicaciones.get_model("ubicaciones", "TipoUbicacion")
    TipoUbicacion._default_manager.update_or_create(
        codigo=CODIGO,
        defaults={"nombre": "Empresa de transporte", "activo": True},
    )


def desactivar_tipo_empresa_transporte(aplicaciones, editor_esquema):
    TipoUbicacion = aplicaciones.get_model("ubicaciones", "TipoUbicacion")
    TipoUbicacion._default_manager.filter(codigo=CODIGO).update(activo=False)


class Migration(migrations.Migration):
    dependencies = [("ubicaciones", "0003_ubicacion_colonia")]

    operations = [
        migrations.RunPython(
            agregar_tipo_empresa_transporte,
            desactivar_tipo_empresa_transporte,
        )
    ]
