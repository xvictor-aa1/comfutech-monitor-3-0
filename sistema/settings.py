#sistema\settings.py
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
        f"Copia 'system.toml.example' a 'system.toml' y rellena los valores."
    )

with _SYSTEM_TOML.open("rb") as _f:
    _cfg = tomllib.load(_f)


def _cfg_get(section: str, key: str, default: str = "") -> str:
    """Wrapper seguro para leer del .toml."""
    return str(_cfg.get(section, {}).get(key, default))


def _cfg_getbool(section: str, key: str, default: bool = False) -> bool:
    val = _cfg.get(section, {}).get(key, default)
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes", "on")
    return bool(val)


def _cfg_getint(section: str, key: str, default: int = 0) -> int:
    try:
        return int(_cfg.get(section, {}).get(key, default))
    except (ValueError, TypeError):
        return default


# ============================================================
# SEGURIDAD
# ============================================================
SECRET_KEY = _cfg_get("django", "secret_key")
if not SECRET_KEY:
    raise RuntimeError(
        "@9b94lze1mkxa^m58e0$#!6y9s5$r(*(v1tk-^s1f9w@aptvpf"
        #"La sección [django] del system.ini debe tener una 'secret_key'."
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
# Cambia `DB_ENGINE` en system.toml (sección [database], clave engine)
# y ajusta los demás campos según el motor elegido.
#
# Ejemplos de system.toml:
#   MySQL:    engine = "mysql"    (requiere: mysqlclient o pymysql)
#   Postgres: engine = "postgres" (requiere: psycopg2-binary)
#   SQLite:   engine = "sqlite"   (sin dependencias extra)
# ============================================================

DB_ENGINE = _cfg_get("database", "engine", "mysql").lower().strip()
DB_NAME = _cfg_get("database", "name", "monitoreo_red")
DB_USER = _cfg_get("database", "user", "monitor")
DB_PASSWORD = _cfg_get("database", "password", "")
DB_HOST = _cfg_get("database", "host", "127.0.0.1")
DB_PORT = _cfg_get("database", "port", "")


if DB_ENGINE == "mysql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": DB_NAME or "comfutech-monitor",
            "USER": DB_USER or "monitor",
            "PASSWORD": DB_PASSWORD,
            "HOST": DB_HOST or "127.0.0.1",
            "PORT": DB_PORT or "3306",
            "OPTIONS": {
                "charset": "utf8mb4",
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }

elif DB_ENGINE in ("postgres", "postgresql", "psql"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": DB_NAME or "postgres",
            "USER": DB_USER,
            "PASSWORD": DB_PASSWORD,
            "HOST": DB_HOST,
            "PORT": DB_PORT or "6543",            # 5432 - conexion por defecto / 6543 Supabase
             # --- Opciones de Django (nivel superior) ---
            "CONN_MAX_AGE": 0,
            "CONN_HEALTH_CHECKS": True,
            "DISABLE_SERVER_SIDE_CURSORS": True,  # ✅ Aquí, no en OPTIONS
            # --- Opciones del driver (se pasan a psycopg) ---
            "OPTIONS": {
                "sslmode": "require",
                "connect_timeout": 10,
            },
        }
    }

elif DB_ENGINE == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / (DB_NAME or "db.sqlite3"),
            "OPTIONS": {
                # Reduce locking en escrituras concurrentes:
                "timeout": 20,
                "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
            },
        }
    }

else:
    raise RuntimeError(
        f"DB_ENGINE='{DB_ENGINE}' no soportado. "
        f"Usa 'mysql', 'postgres' o 'sqlite'."
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

# ❌ Deprecado || Usar en Django 4.2
# STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# ✅ Django 5.1+
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# ============================================================
# EMAIL BACKEND (desde .cfg)
# ============================================================
# El resto de la configuración de email (host, port, etc.)
# ahora se carga desde la tabla `email_config` en runtime.
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
    Aplica la config SMTP de `config.ini` al `django.conf.settings` en
    el arranque, para que los envíos de email funcionen desde el
    primer momento.
    """
    try:
        from core.runtime_config import apply_email_config_to_settings
        apply_email_config_to_settings()
    except Exception:
        pass


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

# Para HTTP (no HTTPS):
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SESSION_COOKIE_SAMESITE = "Lax"  # "Strict" rompe algunos fetch cross-site
