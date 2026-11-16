## sistema/settings.py
"""
Django settings for sistema project.

Sistema de Monitoreo de Red - Comfutech Güigüe
"""
import configparser
import os
import tomllib
from pathlib import Path

# ============================================================
# RUTAS BASE
# ============================================================
BASE_DIR = Path(__file__).resolve().parent.parent
BACKUP_DIR = BASE_DIR / "backup"

# ============================================================
# CARGAR system.toml (bootstrap de Django)
# ============================================================
_SYSTEM_TOML = BASE_DIR / "system.toml"

if not _SYSTEM_TOML.exists():
    raise RuntimeError(
        f"Falta el archivo '{_SYSTEM_TOML}'. "
        f"Copia 'system.toml.example' a 'system.toml' y rellena los valores. "
        f"Puedes usar 'configurador_toml.py' para generarlo desde la GUI."
    )

with _SYSTEM_TOML.open("rb") as _f:
    _cfg = tomllib.load(_f)


def _cfg_get(section: str, key: str, default: str = "") -> str:
    """Wrapper seguro para leer un string del .toml."""
    return str(_cfg.get(section, {}).get(key, default))


def _cfg_getbool(section: str, key: str, default: bool = False) -> bool:
    """Wrapper seguro para leer un bool del .toml."""
    val = _cfg.get(section, {}).get(key, default)
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes", "on")
    return bool(val)


def _cfg_getint(section: str, key: str, default: int = 0) -> int:
    """Wrapper seguro para leer un int del .toml."""
    try:
        return int(_cfg.get(section, {}).get(key, default))
    except (ValueError, TypeError):
        return default


def _cfg_get_section(section: str) -> dict:
    """
    Devuelve una sección completa del TOML como dict.

    Útil para las secciones anidadas ([database.mysql], [database.postgres],
    [database.sqlite], [security]), donde cada valor se lee individualmente
    y no todos tienen por qué existir.
    """
    val = _cfg.get(section, {})
    return val if isinstance(val, dict) else {}


def _get_db_section(engine: str) -> dict:
    """
    Devuelve la sub-sección [database.<engine>] del TOML.

    Args:
        engine: 'mysql' | 'postgres' | 'postgresql' | 'psql' | 'sqlite'.

    Returns:
        dict: la sección anidada o {} si no existe.
    """
    db = _cfg.get("database", {})
    if not isinstance(db, dict):
        return {}
    sub = db.get(engine, {})
    return sub if isinstance(sub, dict) else {}


# ============================================================
# SEGURIDAD
# ============================================================
SECRET_KEY = _cfg_get("django", "secret_key")
if not SECRET_KEY:
    raise RuntimeError(
        "La sección [django] del system.toml debe tener una 'secret_key'. "
        "Usa 'configurador_toml.py' para generarla automáticamente."
    )

# ⚠️ IMPORTANTE: la variable DEBE llamarse DEBUG, no DJANGO_DEBUG.
# Django ignora cualquier otra.
DEBUG = _cfg_getbool("django", "debug", False)

ALLOWED_HOSTS = [
    h.strip()
    for h in _cfg_get("django", "allowed_hosts", "localhost,127.0.0.1").split(",")
    if h.strip()
]

# ============================================================
# APLICACIONES
# ============================================================
INSTALLED_APPS = [
    # Admin personalizado (reemplaza django.contrib.admin)
    "sistema.apps.ComfutechAdminConfig",

    # Apps estándar de Django
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Apps propias
    "inventario",
    "alertas.apps.AlertasConfig",
    "monitoreo",
    "mantenimiento",
    "core.apps.CoreConfig",
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'sistema.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.comfutech_context',
            ],
        },
    },
]

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
WSGI_APPLICATION = 'sistema.wsgi.application'

# ============================================================
# BASE DE DATOS — multi-engine (mysql | postgres | sqlite)
# ============================================================
# El motor se elige con `engine = "..."` en la sección [database]:
#
#   [database]
#   engine = "mysql"      → usa [database.mysql]
#   engine = "postgres"   → usa [database.postgres]   (o "postgresql" / "psql")
#   engine = "sqlite"     → usa [database.sqlite]
#
# Solo la sub-sección del motor elegido se lee; las demás se ignoran
# aunque existan en el archivo.
# ============================================================

DB_ENGINE = _cfg_get("database", "engine", "mysql").lower().strip()

if DB_ENGINE == "mysql":
    _db = _get_db_section("mysql")
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": _db.get("name") or "monitoreo_red",
            "USER": _db.get("user") or "monitor",
            "PASSWORD": _db.get("password", ""),
            "HOST": _db.get("host") or "127.0.0.1",
            "PORT": str(_db.get("port") or "3306"),
            "OPTIONS": {
                "charset": _db.get("charset") or "utf8mb4",
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }

elif DB_ENGINE in ("postgres", "postgresql", "psql"):
    _db = _get_db_section("postgres")
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": _db.get("name") or "postgres",
            "USER": _db.get("user") or "monitor",
            "PASSWORD": _db.get("password", ""),
            "HOST": _db.get("host") or "localhost",
            "PORT": str(_db.get("port") or "5432"),
            # --- Opciones de Django (nivel superior, NO dentro de OPTIONS) ---
            "CONN_MAX_AGE": int(_db.get("conn_max_age", 0)),
            "CONN_HEALTH_CHECKS": bool(_db.get("conn_health_checks", True)),
            "DISABLE_SERVER_SIDE_CURSORS": bool(
                _db.get("disable_server_side_cursors", True)
            ),
            # --- Opciones del driver (se pasan a psycopg) ---
            "OPTIONS": {
                "sslmode": _db.get("sslmode") or "require",
                "connect_timeout": int(_db.get("connect_timeout", 10)),
            },
        }
    }

elif DB_ENGINE == "sqlite":
    _db = _get_db_section("sqlite")
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / (_db.get("name") or "db.sqlite3"),
            "OPTIONS": {
                # Reduce locking en escrituras concurrentes:
                "timeout": int(_db.get("timeout", 20)),
                "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
            },
        }
    }

else:
    raise RuntimeError(
        f"DB_ENGINE='{DB_ENGINE}' no soportado. "
        f"Usa 'mysql', 'postgres' (o 'postgresql' / 'psql') o 'sqlite'."
    )

# ============================================================
# VALIDACIÓN DE CONTRASEÑAS
# ============================================================
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ============================================================
# INTERNACIONALIZACIÓN
# ============================================================
LANGUAGE_CODE = 'es-ve'
TIME_ZONE = 'America/Caracas'
USE_I18N = True
USE_TZ = True

# ============================================================
# ARCHIVOS ESTÁTICOS
# ============================================================
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# ❌ Deprecado en Django 4.2, ELIMINADO en Django 5.1.
# Si estás en Django ≥5.1, esta línea lanza AttributeError al arrancar.
# STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# ✅ STORAGES (introducido en 4.2, obligatorio desde 5.1+).
# Django lo usa internamente para resolver storages de archivos y
# estáticos. Aquí configuramos whitenoise con compresión + manifest.
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# ============================================================
# EMAIL BACKEND (desde .toml)
# ============================================================
# El resto de la configuración de email (host, port, etc.)
# se carga en runtime desde core.runtime_config (config.toml).
EMAIL_BACKEND = _cfg_get(
    "email_backend", "backend",
    "django.core.mail.backends.console.EmailBackend",
)


#EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
#EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
#EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True") == "True"
#EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "False") == "True"
#EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
#EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
#EMAIL_TIMEOUT = 10

#DEFAULT_FROM_EMAIL = os.getenv(
#    "DEFAULT_FROM_EMAIL",
#    "Comfutech Monitor <noreply@comfutech.local>"
#)

# ============================================================
# AUTENTICACIÓN
# ============================================================
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# ============================================================
# COMFUTECH — rutas de config
# ============================================================
COMFUTECH_CONFIG_FILE = BASE_DIR / "config.toml"


# ============================================================
# LOG
# ============================================================
LOG_LEVEL = _cfg_get("django", "log_level", "INFO")

def _bootstrap_email_from_toml():
    """
    Aplica la config SMTP de `config.toml` al `django.conf.settings` en
    el arranque.

    ⚠️ Este bootstrap es una RED DE SEGURIDAD: se ejecuta al final de
    `settings.py`, cuando Django aún no está completamente inicializado.
    Es probable que el import de `core.runtime_config` falle aquí (app
    registry incompleto, etc.) y por eso el `except` NO es silencioso:
    loguea el motivo a nivel DEBUG.

    El bootstrap REAL ocurre en `core/apps.py::CoreConfig.ready()`, que
    se ejecuta cuando Django ya está listo. Los envíos de email tienen
    además un helper defensivo que reintenta antes de cada envío.
    """
    try:
        from core.runtime_config import apply_email_config_to_settings
        apply_email_config_to_settings()
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug(
            "Bootstrap SMTP en settings.py omitido (%s). "
            "Se aplicará en CoreConfig.ready().", e,
        )


try:
    import sys
    if "migrate" not in sys.argv and "makemigrations" not in sys.argv:
        _bootstrap_email_from_toml()
except Exception:
    pass


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "verbose": {
            "format": "{levelname} {asctime} {name} [{process:d}] {message}",
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": BASE_DIR / "logs" / "django.log",
            "maxBytes": 5 * 1024 * 1024,  # 5 MB
            "backupCount": 3,             # hasta 3 archivos rotados
            "formatter": "verbose",
            "encoding": "utf-8",
        },
        "monitor_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": BASE_DIR / "logs" / "monitor.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 3,
            "formatter": "verbose",
            "encoding": "utf-8",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        # Django
        "django": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": ["console"],
            "level": "WARNING",     # silencia las queries SQL
            "propagate": False,
        },
        # Monitor
        "monitoreo": {
            "handlers": ["console", "monitor_file"],
            "level": "INFO",
            "propagate": False,
        },
        # Terceros ruidosos
        "pysnmp": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "influxdb_client": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "urllib3": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "requests": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "apscheduler": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}

# ============================================================
# SEGURIDAD DE COOKIES Y PROXY (configurable vía [security])
# ============================================================
# Todos estos parámetros viven en la sección [security] del system.toml
# y se pueden editar desde la pestaña "Avanzado" de configurador_toml.py.
#
# Valores por defecto (si la sección [security] no existe):
#   SESSION_COOKIE_SECURE       = False
#   CSRF_COOKIE_SECURE          = False
#   SESSION_COOKIE_SAMESITE     = "Lax"
#   USE_X_FORWARDED_HOST        = False
#   SECURE_PROXY_SSL_HEADER     = ("HTTP_X_FORWARDED_PROTO", "https")
#   CSRF_TRUSTED_ORIGINS        = []
# ============================================================

_security = _cfg_get_section("security")

# Cookies solo por HTTPS (activar en producción con HTTPS).
SESSION_COOKIE_SECURE = bool(_security.get("session_cookie_secure", False))
CSRF_COOKIE_SECURE = bool(_security.get("csrf_cookie_secure", False))

# Política SameSite de la cookie de sesión.
# "Lax" (recomendado) · "Strict" (rompe algunos fetch cross-site) · "None"
SESSION_COOKIE_SAMESITE = str(
    _security.get("session_cookie_samesite", "Lax")
).strip() or "Lax"

# Confiar en X-Forwarded-Host del proxy (necesario detrás de Nginx,
# Codespaces, Supabase, etc.).
USE_X_FORWARDED_HOST = bool(_security.get("use_x_forwarded_host", False))

# Header + valor que indican "la petición original era HTTPS".
SECURE_PROXY_SSL_HEADER = (
    str(_security.get("secure_proxy_ssl_header_name", "HTTP_X_FORWARDED_PROTO")).strip(),
    str(_security.get("secure_proxy_ssl_header_value", "https")).strip(),
)

# Orígenes de confianza para la verificación CSRF.
# Cada entrada debe empezar por http:// o https://.
_origins = _security.get("csrf_trusted_origins", [])
if isinstance(_origins, list):
    CSRF_TRUSTED_ORIGINS = [str(o).strip() for o in _origins if str(o).strip()]
elif isinstance(_origins, str):
    # Tolerancia por si alguien lo pone como string separado por comas.
    CSRF_TRUSTED_ORIGINS = [s.strip() for s in _origins.split(",") if s.strip()]
else:
    CSRF_TRUSTED_ORIGINS = []