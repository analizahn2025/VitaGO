"""Settings shared by all VitaGo environments and deployment modes."""

import os
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
# La web usa Bearer JWT; solo los orígenes explícitos pueden leer la API.
CORS_ALLOWED_ORIGINS = env.list("ORIGENES_WEB_PERMITIDOS", default=[])
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_CREDENTIALS = False
CORS_URLS_REGEX = r"^/api/v1/"
CORS_EXPOSE_HEADERS = ["Retry-After", "Server-Timing"]
DEFAULT_EXCEPTION_REPORTER_FILTER = "apps.nucleo.seguridad.FiltroInformeErroresSeguro"
DEFAULT_EXCEPTION_REPORTER = "apps.nucleo.seguridad.InformeErroresSeguro"

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
    "corsheaders",
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
    "apps.rutas.apps.ConfiguracionRutas",
    "apps.notificaciones.apps.ConfiguracionNotificaciones",
    "apps.evidencias.apps.ConfiguracionEvidencias",
    "apps.jornadas.apps.ConfiguracionJornadas",
    "apps.seguimiento.apps.ConfiguracionSeguimiento",
    "apps.incidencias.apps.ConfiguracionIncidencias",
]

MIDDLEWARE = [
    "apps.nucleo.middleware.MiddlewareRendimientoAPI",
    "corsheaders.middleware.CorsMiddleware",
    "apps.nucleo.seguridad.MiddlewareErroresSegurosAPI",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "apps.nucleo.middleware.MiddlewareRecuperacionCierre",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

REGISTRAR_RENDIMIENTO_API = env.bool(
    "REGISTRAR_RENDIMIENTO_API",
    default=False,
)
HABILITAR_RECUPERACION_CIERRE = env.bool("HABILITAR_RECUPERACION_CIERRE", default=True)
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

# Captura, envío y uso operativo del GPS son controles independientes.
ANTIGUEDAD_GPS_ASIGNACION_SEGUNDOS = env.int("ANTIGUEDAD_GPS_ASIGNACION_SEGUNDOS", default=120)
PRECISION_GPS_ASIGNACION_METROS = env.float("PRECISION_GPS_ASIGNACION_METROS", default=50)
ASIGNACION_REQUIERE_GPS_VIGENTE = env.bool("ASIGNACION_REQUIERE_GPS_VIGENTE", default=True)
INTERVALO_GPS_MAXIMO_SEGUNDOS = env.int("INTERVALO_GPS_MAXIMO_SEGUNDOS", default=30)
DESPLAZAMIENTO_GPS_MINIMO_METROS = env.float("DESPLAZAMIENTO_GPS_MINIMO_METROS", default=5)
COBERTURA_GPS_MINIMA_PORCENTAJE = env.float("COBERTURA_GPS_MINIMA_PORCENTAJE", default=90)
INTERVALO_GPS_CAPTURA_MOVIMIENTO_SEGUNDOS = env.int("INTERVALO_GPS_CAPTURA_MOVIMIENTO_SEGUNDOS", default=5)
INTERVALO_GPS_CAPTURA_DETENIDO_SEGUNDOS = env.int("INTERVALO_GPS_CAPTURA_DETENIDO_SEGUNDOS", default=15)
INTERVALO_GPS_ENVIO_SEGUNDOS = env.int("INTERVALO_GPS_ENVIO_SEGUNDOS", default=20)
LLEGADAS_AUTOMATICAS_HABILITADAS = env.bool("LLEGADAS_AUTOMATICAS_HABILITADAS", default=True)
RADIO_LLEGADA_METROS = env.float("RADIO_LLEGADA_METROS", default=50)
PERMANENCIA_LLEGADA_SEGUNDOS = env.int("PERMANENCIA_LLEGADA_SEGUNDOS", default=10)
MINIMO_PUNTOS_LLEGADA = env.int("MINIMO_PUNTOS_LLEGADA", default=3)
PRECISION_LLEGADA_MAXIMA_METROS = env.float("PRECISION_LLEGADA_MAXIMA_METROS", default=20)
ANTIGUEDAD_LLEGADA_MAXIMA_SEGUNDOS = env.int("ANTIGUEDAD_LLEGADA_MAXIMA_SEGUNDOS", default=30)
for nombre in (
    "ANTIGUEDAD_GPS_ASIGNACION_SEGUNDOS", "PRECISION_GPS_ASIGNACION_METROS",
    "INTERVALO_GPS_MAXIMO_SEGUNDOS", "DESPLAZAMIENTO_GPS_MINIMO_METROS",
    "INTERVALO_GPS_CAPTURA_MOVIMIENTO_SEGUNDOS", "INTERVALO_GPS_CAPTURA_DETENIDO_SEGUNDOS",
    "INTERVALO_GPS_ENVIO_SEGUNDOS",
    "RADIO_LLEGADA_METROS", "PERMANENCIA_LLEGADA_SEGUNDOS",
    "PRECISION_LLEGADA_MAXIMA_METROS", "ANTIGUEDAD_LLEGADA_MAXIMA_SEGUNDOS",
):
    if globals()[nombre] <= 0:
        raise ImproperlyConfigured(f"{nombre} debe ser mayor que cero.")
if not 0 < COBERTURA_GPS_MINIMA_PORCENTAJE <= 100:
    raise ImproperlyConfigured("COBERTURA_GPS_MINIMA_PORCENTAJE debe estar entre 0 y 100.")
if INTERVALO_GPS_CAPTURA_MOVIMIENTO_SEGUNDOS > INTERVALO_GPS_MAXIMO_SEGUNDOS or INTERVALO_GPS_CAPTURA_DETENIDO_SEGUNDOS > INTERVALO_GPS_MAXIMO_SEGUNDOS:
    raise ImproperlyConfigured("Los intervalos de captura GPS no pueden superar INTERVALO_GPS_MAXIMO_SEGUNDOS.")
if not 3 <= MINIMO_PUNTOS_LLEGADA <= 60:
    raise ImproperlyConfigured("MINIMO_PUNTOS_LLEGADA debe estar entre 3 y 60.")
if PERMANENCIA_LLEGADA_SEGUNDOS > 120:
    raise ImproperlyConfigured("PERMANENCIA_LLEGADA_SEGUNDOS no puede superar la ventana de 120 segundos.")

ROOT_URLCONF = "config.urls"

# Solo un POST autorizado puede consumir Routes API; las lecturas nunca llaman a Google.
CLAVE_API_GOOGLE_MAPS = env.str("CLAVE_API_GOOGLE_MAPS", default="").strip()
HABILITAR_RUTAS_GOOGLE = env.bool("HABILITAR_RUTAS_GOOGLE", default=False)
RUTAS_GOOGLE_TIMEOUT_SEGUNDOS = env.float("RUTAS_GOOGLE_TIMEOUT_SEGUNDOS", default=5)
RUTAS_GOOGLE_LIMITE_DIARIO = env.int("RUTAS_GOOGLE_LIMITE_DIARIO", default=50)
RUTAS_GOOGLE_LIMITE_MENSUAL = env.int("RUTAS_GOOGLE_LIMITE_MENSUAL", default=500)
RUTAS_GOOGLE_INTENTOS_POR_VERSION = env.int("RUTAS_GOOGLE_INTENTOS_POR_VERSION", default=2)
RUTAS_GOOGLE_CACHE_HORAS = env.int("RUTAS_GOOGLE_CACHE_HORAS", default=24)
if not 0 < RUTAS_GOOGLE_TIMEOUT_SEGUNDOS <= 10:
    raise ImproperlyConfigured("RUTAS_GOOGLE_TIMEOUT_SEGUNDOS debe estar entre 0 y 10.")
if not 1 <= RUTAS_GOOGLE_CACHE_HORAS <= 24:
    raise ImproperlyConfigured("RUTAS_GOOGLE_CACHE_HORAS debe estar entre 1 y 24.")
if not 1 <= RUTAS_GOOGLE_INTENTOS_POR_VERSION <= 2:
    raise ImproperlyConfigured("RUTAS_GOOGLE_INTENTOS_POR_VERSION debe estar entre 1 y 2.")
for nombre in ("RUTAS_GOOGLE_LIMITE_DIARIO", "RUTAS_GOOGLE_LIMITE_MENSUAL", "RUTAS_GOOGLE_INTENTOS_POR_VERSION"):
    if globals()[nombre] < 1:
        raise ImproperlyConfigured(f"{nombre} debe ser mayor que cero.")

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
ZONA_HORARIA_RESUMEN_SOLICITANTE = env.str(
    "ZONA_HORARIA_RESUMEN_SOLICITANTE", default="America/Tegucigalpa"
).strip()
try:
    ZoneInfo(ZONA_HORARIA_RESUMEN_SOLICITANTE)
except (ValueError, ZoneInfoNotFoundError) as error:
    raise ImproperlyConfigured(
        "ZONA_HORARIA_RESUMEN_SOLICITANTE debe ser una zona horaria IANA válida."
    ) from error
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
PIXELES_MAXIMOS_EVIDENCIA = env.int("PIXELES_MAXIMOS_EVIDENCIA", default=40000000)
if PIXELES_MAXIMOS_EVIDENCIA < 1:
    raise ImproperlyConfigured("PIXELES_MAXIMOS_EVIDENCIA debe ser mayor o igual a 1.")
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
