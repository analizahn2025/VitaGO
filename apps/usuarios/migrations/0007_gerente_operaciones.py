from django.db import migrations


CODIGO_ROL = "GERENTE_OPERACIONES"
CODIGO_PERMISO = "solicitud.crear_envio_especial"
PERMISOS_ROL = {
    "empresa.ver",
    "sucursal.ver",
    "usuario.ver",
    "ubicacion.ver",
    "solicitud.crear",
    "solicitud.crear_envio_especial",
    "solicitud.ver",
    "solicitud.asignar",
    "solicitud.reasignar",
    "solicitud.cancelar",
    "solicitud.ver_seguimiento",
    "repartidor.ver",
    "repartidor.administrar",
    "repartidor.ver_ubicacion",
    "ruta.ver",
    "ruta.administrar",
    "evidencia.ver",
    "incidencia.revisar",
    "jornada.ver",
    "vehiculo.ver",
    "reporte.ver",
}


def agregar_gerente_operaciones(aplicaciones, editor_esquema):
    Rol = aplicaciones.get_model("usuarios", "Rol")
    Permiso = aplicaciones.get_model("usuarios", "Permiso")
    PermisoRol = aplicaciones.get_model("usuarios", "PermisoRol")

    rol, _ = Rol._default_manager.update_or_create(
        codigo=CODIGO_ROL,
        defaults={
            "nombre": "Gerente de operaciones",
            "descripcion": (
                "Dirección operativa corporativa y creación de envíos especiales."
            ),
            "activo": True,
            "permite_alcance_global": False,
            "permite_alcance_empresa": True,
            "permite_alcance_sucursal": False,
        },
    )
    permiso_especial, _ = Permiso._default_manager.update_or_create(
        codigo=CODIGO_PERMISO,
        defaults={
            "nombre": "Crear envíos especiales",
            "descripcion": (
                "Crear envíos corporativos especiales con destino descriptivo."
            ),
            "activo": True,
        },
    )
    permisos = {
        permiso.codigo: permiso
        for permiso in Permiso._default_manager.filter(codigo__in=PERMISOS_ROL)
    }
    permisos[CODIGO_PERMISO] = permiso_especial
    for codigo in PERMISOS_ROL:
        permiso = permisos.get(codigo)
        if permiso is not None:
            PermisoRol._default_manager.update_or_create(
                rol=rol,
                permiso=permiso,
                defaults={"activo": True},
            )


def desactivar_gerente_operaciones(aplicaciones, editor_esquema):
    Rol = aplicaciones.get_model("usuarios", "Rol")
    Permiso = aplicaciones.get_model("usuarios", "Permiso")
    PermisoRol = aplicaciones.get_model("usuarios", "PermisoRol")

    PermisoRol._default_manager.filter(rol__codigo=CODIGO_ROL).update(activo=False)
    Rol._default_manager.filter(codigo=CODIGO_ROL).update(activo=False)
    permiso = Permiso._default_manager.filter(codigo=CODIGO_PERMISO).first()
    if permiso and not PermisoRol._default_manager.filter(
        permiso=permiso,
        activo=True,
    ).exists():
        Permiso._default_manager.filter(pk=permiso.pk).update(activo=False)


class Migration(migrations.Migration):
    dependencies = [("usuarios", "0006_permiso_registrar_ubicacion")]

    operations = [
        migrations.RunPython(
            agregar_gerente_operaciones,
            desactivar_gerente_operaciones,
        )
    ]
