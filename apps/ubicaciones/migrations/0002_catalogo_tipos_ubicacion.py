from django.db import migrations


TIPOS_UBICACION = {
    "HOSPITAL": "Hospital",
    "CLINICA": "Clínica",
    "LABORATORIO_CLINICO": "Laboratorio clínico",
    "CONSULTORIO": "Consultorio",
    "FARMACIA": "Farmacia",
    "BANCO_SANGRE": "Banco de sangre",
    "CENTRO_IMAGENES": "Centro de imágenes",
    "CENTRO_MEDICO": "Centro médico",
    "SUCURSAL": "Sucursal",
    "RESIDENCIA": "Residencia",
    "EMPRESA": "Empresa",
    "OTRO": "Otro",
}


def crear_catalogo_tipos_ubicacion(aplicaciones, editor_esquema):
    TipoUbicacion = aplicaciones.get_model("ubicaciones", "TipoUbicacion")

    for codigo, nombre in TIPOS_UBICACION.items():
        TipoUbicacion._default_manager.update_or_create(
            codigo=codigo,
            defaults={
                "nombre": nombre,
                "activo": True,
            },
        )


def desactivar_catalogo_tipos_ubicacion(aplicaciones, editor_esquema):
    TipoUbicacion = aplicaciones.get_model("ubicaciones", "TipoUbicacion")
    TipoUbicacion._default_manager.filter(
        codigo__in=TIPOS_UBICACION,
    ).update(activo=False)


class Migration(migrations.Migration):
    dependencies = [
        ("ubicaciones", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            crear_catalogo_tipos_ubicacion,
            desactivar_catalogo_tipos_ubicacion,
        ),
    ]
