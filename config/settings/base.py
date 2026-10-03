"""Settings shared by all VitaGo environments and deployment modes."""

import os
from datetime import timedelta
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

from config.ejecucion import (
    Funcionalidades,
    ModoAplicacion,
    ProveedorAutenticacion,
    interpretar_modo_aplicacion,
    interpretar_proveedor_autenticacion,
)

BASE_DIR = Path(__file__).resolve().parents[2]

env = environ.Env()
env_file = BASE_DIR / ".env"
if env_file.is_file():
    environ.Env.read_env(env_file)

nombre_archivo_adicional = os.environ.get(
    "ARCHIVO_ENTORNO_ADICIONAL",
    "",
).strip()
if nombre_archivo_adicional:
    if (
        Path(nombre_archivo_adicional).name != nombre_archivo_adicional
        or not nombre_archivo_adicional.startswith(".env.")
    ):
        raise ImproperlyConfigured(
            "ARCHIVO_ENTORNO_ADICIONAL debe indicar un archivo .env.* "
            "ubicado en la raíz del backend."
        )
    archivo_entorno_adicional = BASE_DIR / nombre_archivo_adicional
    if not archivo_entorno_adicional.is_file():
        raise ImproperlyConfigured(
            f"No existe el archivo de entorno {nombre_archivo_adicional}."
        )
    environ.Env.read_env(archivo_entorno_adicional, overwrite=True)

NOMBRE_APLICACION = env.str("NOMBRE_APLICACION", default="VitaGo")
ENTORNO = env.str("ENTORNO", default="LOCAL").upper()
MODO_APLICACION = interpretar_modo_aplicacion(
    env.str("MODO_APLICACION", default="CORPORATIVO")
).value
proveedor_predeterminado = (
    ProveedorAutenticacion.LOCAL
    if MODO_APLICACION == ModoAplicacion.EXTERNO
    else ProveedorAutenticacion.JWT_CORPORATIVO
)
PROVEEDOR_AUTENTICACION = interpretar_proveedor_autenticacion(
    env.str(
        "PROVEEDOR_AUTENTICACION",
        default=proveedor_predeterminado.value,
    )
).value

if (
    MODO_APLICACION == ModoAplicacion.EXTERNO
    and PROVEEDOR_AUTENTICACION != ProveedorAutenticacion.LOCAL
):
    raise ImproperlyConfigured(
        "VitaGo Network requiere PROVEEDOR_AUTENTICACION=LOCAL."
    )

SECRET_KEY = env.str("CLAVE_SECRETA", default="")
DEBUG = env.bool("DEPURACION", default=False)
ALLOWED_HOSTS = env.list("SERVIDORES_PERMITIDOS", default=[])

FUNCIONALIDADES = Funcionalidades(
    tarifas=env.bool("FUNCIONALIDAD_TARIFAS", default=False),
    repartidores_compartidos=env.bool(
        "FUNCIONALIDAD_REPARTIDORES_COMPARTIDOS",
        default=False,
    ),
    mantenimiento_flota=env.bool(
        "FUNCIONALIDAD_MANTENIMIENTO_FLOTA",
        default=False,
    ),
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.nucleo.apps.ConfiguracionNucleo",
    "apps.geografia.apps.ConfiguracionGeografia",
    "apps.organizaciones.apps.ConfiguracionOrganizaciones",
    "apps.ubicaciones.apps.ConfiguracionUbicaciones",
    "apps.usuarios.apps.ConfiguracionUsuarios",
    "apps.autenticacion.apps.ConfiguracionAutenticacion",
    "apps.flota.apps.ConfiguracionFlota",
    "apps.repartidores.apps.ConfiguracionRepartidores",
    "apps.solicitudes.apps.ConfiguracionSolicitudes",
    "apps.notificaciones.apps.ConfiguracionNotificaciones",
    "apps.evidencias.apps.ConfiguracionEvidencias",
    "apps.jornadas.apps.ConfiguracionJornadas",
    "apps.seguimiento.apps.ConfiguracionSeguimiento",
    "apps.incidencias.apps.ConfiguracionIncidencias",
]

MIDDLEWARE = [
    "apps.nucleo.middleware.MiddlewareRendimientoAPI",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

REGISTRAR_RENDIMIENTO_API = env.bool(
    "REGISTRAR_RENDIMIENTO_API",
    default=False,
)
UMBRAL_API_LENTA_MS = env.float(
    "UMBRAL_API_LENTA_MS",
    default=1000.0,
)
PRECISION_GPS_MAXIMA_METROS = env.float(
    "PRECISION_GPS_MAXIMA_METROS",
    default=100.0,
)
VELOCIDAD_GPS_MAXIMA_METROS_SEGUNDO = env.float(
    "VELOCIDAD_GPS_MAXIMA_METROS_SEGUNDO",
    default=55.0,
)
if PRECISION_GPS_MAXIMA_METROS <= 0:
    raise ImproperlyConfigured(
        "PRECISION_GPS_MAXIMA_METROS debe ser mayor que cero."
    )
if VELOCIDAD_GPS_MAXIMA_METROS_SEGUNDO <= 0:
    raise ImproperlyConfigured(
        "VELOCIDAD_GPS_MAXIMA_METROS_SEGUNDO debe ser mayor que cero."
    )

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": env.db_url(
        "URL_BASE_DATOS",
        default="postgresql://vitago:vitago@127.0.0.1:5432/vitago",
    )
}
NOMBRE_BASE_DATOS = env.str("NOMBRE_BASE_DATOS", default="").strip()
if NOMBRE_BASE_DATOS:
    DATABASES["default"]["NAME"] = NOMBRE_BASE_DATOS

AUTH_USER_MODEL = "usuarios.Usuario"

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        )
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"
    },
]

LANGUAGE_CODE = env.str("CODIGO_IDIOMA", default="es")
TIME_ZONE = env.str("ZONA_HORARIA_PREDETERMINADA", default="UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
raiz_archivos_configurada = Path(
    env.str(
        "RAIZ_ARCHIVOS",
        default=str(BASE_DIR / "media" / MODO_APLICACION.lower()),
    )
)
MEDIA_ROOT = (
    raiz_archivos_configurada
    if raiz_archivos_configurada.is_absolute()
    else BASE_DIR / raiz_archivos_configurada
)
MEDIA_URL = "/media/"
TAMANO_MAXIMO_EVIDENCIA_MB = env.int(
    "TAMANO_MAXIMO_EVIDENCIA_MB",
    default=10,
)
if TAMANO_MAXIMO_EVIDENCIA_MB < 1:
    raise ImproperlyConfigured(
        "TAMANO_MAXIMO_EVIDENCIA_MB debe ser mayor o igual a 1."
    )
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

ALGORITMO_JWT_LOCAL = env.str(
    "ALGORITMO_JWT_LOCAL",
    default=env.str("ALGORITMO_JWT_EXTERNO", default="HS256"),
)
CLAVE_FIRMA_JWT_LOCAL = env.str(
    "CLAVE_FIRMA_JWT_LOCAL",
    default=env.str("CLAVE_FIRMA_JWT_EXTERNO", default=""),
)
EMISOR_JWT_LOCAL = env.str(
    "EMISOR_JWT_LOCAL",
    default=env.str("EMISOR_JWT_EXTERNO", default="vitago-network"),
)
AUDIENCIA_JWT_LOCAL = env.str(
    "AUDIENCIA_JWT_LOCAL",
    default=env.str("AUDIENCIA_JWT_EXTERNO", default="vitago-movil"),
)
MINUTOS_TOKEN_ACCESO = env.int("MINUTOS_TOKEN_ACCESO", default=15)
DIAS_TOKEN_REFRESCO = env.int("DIAS_TOKEN_REFRESCO", default=7)
CLAVE_HASH_TOKEN_REFRESCO_LOCAL = env.str(
    "CLAVE_HASH_TOKEN_REFRESCO_LOCAL",
    default=env.str("CLAVE_HASH_TOKEN_REFRESCO", default=""),
)

ALGORITMO_JWT_CORPORATIVO = env.str(
    "ALGORITMO_JWT_CORPORATIVO",
    default="RS256",
)
CLAVE_PUBLICA_JWT_CORPORATIVO = env.str(
    "CLAVE_PUBLICA_JWT_CORPORATIVO",
    default="",
).replace("\\n", "\n")
EMISOR_JWT_CORPORATIVO = env.str("EMISOR_JWT_CORPORATIVO", default="")
AUDIENCIA_JWT_CORPORATIVO = env.str("AUDIENCIA_JWT_CORPORATIVO", default="")
CLAIM_IDENTIDAD_JWT_CORPORATIVO = env.str(
    "CLAIM_IDENTIDAD_JWT_CORPORATIVO",
    default="sub",
)
SEGUNDOS_TOLERANCIA_RELOJ_JWT = env.int(
    "SEGUNDOS_TOLERANCIA_RELOJ_JWT",
    default=30,
)

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=MINUTOS_TOKEN_ACCESO),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=DIAS_TOKEN_REFRESCO),
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": False,
    "UPDATE_LAST_LOGIN": False,
    "ALGORITHM": ALGORITMO_JWT_LOCAL,
    "SIGNING_KEY": CLAVE_FIRMA_JWT_LOCAL,
    "AUDIENCE": AUDIENCIA_JWT_LOCAL,
    "ISSUER": EMISOR_JWT_LOCAL,
    "LEEWAY": SEGUNDOS_TOLERANCIA_RELOJ_JWT,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "usuario_id",
    "TOKEN_TYPE_CLAIM": "tipo_token",
    "JTI_CLAIM": "jti",
}

REST_FRAMEWORK = {
    "EXCEPTION_HANDLER": "apps.nucleo.excepciones.manejador_excepciones",
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "apps.autenticacion.autenticadores.AutenticacionVitaGo",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_RENDERER_CLASSES": (
        "rest_framework.renderers.JSONRenderer",
    ),
}
