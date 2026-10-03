from django.db import migrations


TIPOS_SERVICIO = {
    "MUESTRA_BIOLOGICA": (
        "Muestra biológica",
        "Traslado controlado de muestras biológicas.",
    ),
    "MEDICAMENTO": (
        "Medicamento",
        "Traslado de medicamentos y productos farmacéuticos.",
    ),
    "REACTIVO": (
        "Reactivo",
        "Traslado de reactivos para laboratorio.",
    ),
    "INSUMO_MEDICO": (
        "Insumo médico",
        "Traslado de suministros e insumos médicos.",
    ),
    "DOCUMENTO": (
        "Documento",
        "Traslado de documentación administrativa o clínica autorizada.",
    ),
    "RESULTADO": (
        "Resultado",
        "Traslado de resultados y documentos de laboratorio.",
    ),
    "EQUIPO": (
        "Equipo",
        "Traslado de equipo médico o de laboratorio.",
    ),
    "PAQUETE": (
        "Paquete",
        "Traslado de paquetes de uso operativo.",
    ),
    "OTRO": (
        "Otro",
        "Servicio logístico no incluido en los tipos anteriores.",
    ),
}


def crear_catalogo(aplicaciones, editor_esquema):
    TipoServicio = aplicaciones.get_model("solicitudes", "TipoServicio")
    for codigo, (nombre, descripcion) in TIPOS_SERVICIO.items():
        TipoServicio._default_manager.update_or_create(
            codigo=codigo,
            defaults={
                "nombre": nombre,
                "descripcion": descripcion,
                "activo": True,
            },
        )


def desactivar_catalogo(aplicaciones, editor_esquema):
    TipoServicio = aplicaciones.get_model("solicitudes", "TipoServicio")
    TipoServicio._default_manager.filter(
        codigo__in=TIPOS_SERVICIO
    ).update(activo=False)


class Migration(migrations.Migration):
    dependencies = [
        ("solicitudes", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(crear_catalogo, desactivar_catalogo),
    ]
