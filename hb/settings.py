"""
Harbour Hub - Django Settings (cleaned & production-ready)
"""

import os
from pathlib import Path
from datetime import timedelta
from decouple import config, Csv
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent

# =============================================================================
# CORE SETTINGS
# =============================================================================

DEBUG = config("DEBUG", default=False, cast=bool)
ENVIRONMENT = config("ENVIRONMENT", default="development")

SECRET_KEY = config("SECRET_KEY", default="change-this-in-production")

ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv()
)

SITE_URL = config("SITE_URL", default="http://localhost:8000")
SITE_NAME = config("SITE_NAME", default="Harbour Hub")

# =============================================================================
# APPLICATIONS
# =============================================================================

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    "mptt",
    "django_celery_beat"
]

if DEBUG and config("ENABLE_DEBUG_TOOLBAR", default=False, cast=bool):
    THIRD_PARTY_APPS.append("debug_toolbar")

if config("ENABLE_DJANGO_EXTENSIONS", default=False, cast=bool):
    THIRD_PARTY_APPS.append("django_extensions")

if config("USE_S3", default=False, cast=bool):
    THIRD_PARTY_APPS.append("storages")

LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.listings",
    "apps.categories",
    "apps.inquiries",
    "apps.admin_panel",
    "apps.analytics",
    "apps.health",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# =============================================================================
# MIDDLEWARE
# =============================================================================

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

if DEBUG and config("ENABLE_DEBUG_TOOLBAR", default=False, cast=bool):
    MIDDLEWARE.append("debug_toolbar.middleware.DebugToolbarMiddleware")

# =============================================================================
# RATE LIMIT (global middleware)
# =============================================================================
if config("RATELIMIT_ENABLE", default=False, cast=bool):
    MIDDLEWARE.insert(
        0,  # add first so it runs before auth/session
        "django_ratelimit.middleware.RatelimitMiddleware"
    )
    RATELIMIT_ENABLE = True
    RATELIMIT_USE_CACHE = "default"
else:
    RATELIMIT_ENABLE = False


ROOT_URLCONF = "hb.urls"

# =============================================================================
# TEMPLATES
# =============================================================================

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "hb.wsgi.application"

# =============================================================================
# DATABASE
# =============================================================================

DATABASE_URL = config("DATABASE_URL", default=None)

if DATABASE_URL:
    import dj_database_url

    DATABASES = {"default": dj_database_url.parse(DATABASE_URL)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": config("DB_NAME", default="harbour_hub"),
            "USER": config("DB_USER", default="postgres"),
            "PASSWORD": config("DB_PASSWORD", default="password"),
            "HOST": config("DB_HOST", default="localhost"),
            "PORT": config("DB_PORT", default="5432"),
            "CONN_MAX_AGE": config("DB_CONN_MAX_AGE", default=600, cast=int),
        }
    }

AUTH_USER_MODEL = "accounts.User"

# =============================================================================
# PASSWORD VALIDATORS
# =============================================================================

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": config("PASSWORD_MIN_LENGTH", default=8, cast=int)},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# =============================================================================
# I18N / TZ
# =============================================================================

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# =============================================================================
# STATIC & MEDIA (AWS S3)
# =============================================================================

USE_S3 = config("USE_S3", default=False, cast=bool)

if USE_S3:
    AWS_ACCESS_KEY_ID = config("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = config("AWS_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME = config("AWS_STORAGE_BUCKET_NAME")
    AWS_S3_REGION_NAME = config(
        "AWS_S3_REGION_NAME", default="eu-north-1")  # Stockholm
    AWS_DEFAULT_ACL = None  # ✅ ensures no ACLs are applied

    AWS_S3_CUSTOM_DOMAIN = config(
        "AWS_S3_CUSTOM_DOMAIN",
        default=f"{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com"
    )

    # ✅ remove any ACL parameter entirely
    AWS_S3_OBJECT_PARAMETERS = {
        "CacheControl": "max-age=86400",
    }

    AWS_QUERYSTRING_AUTH = False
    AWS_S3_FILE_OVERWRITE = False

    # Storage backends
    STATICFILES_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
    DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"

    STATIC_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/static/"
    MEDIA_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/media/"
else:
    STATIC_ROOT = config(
        "STATIC_ROOT", default=os.path.join(BASE_DIR, "staticfiles"))
    MEDIA_ROOT = config("MEDIA_ROOT", default=os.path.join(BASE_DIR, "media"))
    STATIC_URL = "/static/"
    MEDIA_URL = "/media/"

# =============================================================================
# CACHE
# =============================================================================

REDIS_URL = config(
    "REDIS_URL",
)

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "TIMEOUT": config("CACHE_TIMEOUT", default=3600, cast=int),
        "KEY_PREFIX": config("CACHE_KEY_PREFIX", default="harbour_hub"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "CONNECTION_POOL_KWARGS": {
                "max_connections": 100,
                "ssl_cert_reqs": None,  # ensures no SSL warnings
            },
            "SSL": True,
        },
    }
}


# Optional (recommended): store user sessions in Redis
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"

# Optional: cache timeout defaults
CACHE_TTL = 60 * 15  # 15 minutes

# # =============================================================================
# # EMAIL
# # =============================================================================

# EMAIL_BACKEND = config(
#     "EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
# EMAIL_HOST = config("EMAIL_HOST", default="localhost")
# EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
# EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
# EMAIL_USE_SSL = config("EMAIL_USE_SSL", default=False, cast=bool)
# EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
# EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")

# DEFAULT_FROM_EMAIL = config(
#     "DEFAULT_FROM_EMAIL", default="noreply@harbourhub.com")
# SERVER_EMAIL = config("SERVER_EMAIL", default="server@harbourhub.com")
# ADMIN_EMAIL = config("ADMIN_EMAIL", default="admin@harbourhub.com")
# SUPPORT_EMAIL = config("SUPPORT_EMAIL", default="support@harbourhub.com")
# SECURITY_EMAIL = config("SECURITY_EMAIL", default="security@harbourhub.com")
# SEND_WELCOME_EMAIL = config("SEND_WELCOME_EMAIL", default=True, cast=bool)

# =============================================================================
# EMAIL (SendGrid)
# =============================================================================

EMAIL_BACKEND = config(
    "EMAIL_BACKEND", default="sendgrid_backend.SendgridBackend"
)

SENDGRID_API_KEY = config("SENDGRID_API_KEY", default=None)
SENDGRID_SANDBOX_MODE_IN_DEBUG = config(
    "SENDGRID_SANDBOX_MODE_IN_DEBUG", default=False, cast=bool
)
SENDGRID_ECHO_TO_STDOUT = config(
    "SENDGRID_ECHO_TO_STDOUT", default=False, cast=bool
)

DEFAULT_FROM_EMAIL = config(
    "DEFAULT_FROM_EMAIL", default="harbourhub2025@gmail.com"
)
SERVER_EMAIL = config("SERVER_EMAIL", default="harbourhub2025@gmail.com")
ADMIN_EMAIL = config("ADMIN_EMAIL", default="harbourhub2025@gmail.com")
SUPPORT_EMAIL = config("SUPPORT_EMAIL", default="harbourhub2025@gmail.com")
SECURITY_EMAIL = config("SECURITY_EMAIL", default="security@harbourhub.com")
SEND_WELCOME_EMAIL = config("SEND_WELCOME_EMAIL", default=True, cast=bool)

# =============================================================================
# DRF
# =============================================================================

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": config("DEFAULT_PAGE_SIZE", default=20, cast=int),
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": config("API_RATE_LIMIT", default="100/hour"),
        "user": config("API_RATE_LIMIT", default="1000/hour"),
        "burst": config("API_BURST_LIMIT", default="100/minute"),
    },
}

# =============================================================================
# SPECTACULAR (API Docs)
# =============================================================================
SPECTACULAR_SETTINGS = {
    "TITLE": config("API_TITLE", default="Harbour Hub API"),
    "DESCRIPTION": config("API_DESCRIPTION", default="Oil & Gas / Marine Equipment Marketplace API"),
    "VERSION": config("API_VERSION", default="1.0.0"),
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}


# =============================================================================
# JWT
# =============================================================================

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=config("JWT_ACCESS_TOKEN_LIFETIME_HOURS", default=24, cast=int)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=config("JWT_REFRESH_TOKEN_LIFETIME_DAYS", default=7, cast=int)),
    "ROTATE_REFRESH_TOKENS": config("JWT_ROTATE_REFRESH_TOKENS", default=True, cast=bool),
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# =============================================================================
# CORS & CSRF
# =============================================================================

CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="http://localhost:3000,http://127.0.0.1:3000",
    cast=Csv(),
)
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_ALL_ORIGINS = DEBUG and config(
    "CORS_ALLOW_ALL_ORIGINS", default=False, cast=bool)

CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default="http://localhost:3000,http://127.0.0.1:3000",
    cast=Csv(),
)

# =============================================================================
# SECURITY HEADERS
# =============================================================================
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"


# =============================================================================
# LOGGING
# =============================================================================

LOG_LEVEL = config("LOG_LEVEL", default="INFO")
LOG_FILE_PATH = config("LOG_FILE_PATH", default="logs/harbour_hub.log")
os.makedirs(os.path.dirname(LOG_FILE_PATH), exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{levelname} {asctime} {module} {message}", "style": "{"},
        "simple": {"format": "{levelname} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_FILE_PATH,
            "maxBytes": config("LOG_MAX_SIZE_MB", default=100, cast=int) * 1024 * 1024,
            "backupCount": config("LOG_BACKUP_COUNT", default=5, cast=int),
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console", "file"], "level": LOG_LEVEL},
    "loggers": {
        "django": {"handlers": ["console", "file"], "level": LOG_LEVEL, "propagate": False},
        "harbour_hub": {"handlers": ["console", "file"], "level": LOG_LEVEL, "propagate": False},
    },
}

# =============================================================================
# SENTRY
# =============================================================================

SENTRY_DSN = config("SENTRY_DSN", default=None)
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=True,
        environment=ENVIRONMENT,
    )

# =============================================================================
# CELERY
# =============================================================================

CELERY_BROKER_URL = config("CELERY_BROKER_URL", default=f"{REDIS_URL}/1")
CELERY_RESULT_BACKEND = config(
    "CELERY_RESULT_BACKEND", default=f"{REDIS_URL}/2")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# Secure Redis SSL (important for Aiven)
BROKER_USE_SSL = {"ssl_cert_reqs": None}
CELERY_REDIS_BACKEND_USE_SSL = {"ssl_cert_reqs": None}

# Retry connection on startup to avoid race conditions
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

CELERY_BEAT_SCHEDULE = {
    # run expire_listings_task every hour
    "expire-listings-every-hour": {
        "task": "apps.listings.tasks.expire_listings_task",
        "schedule": crontab(minute=0, hour="*/1"),
    },

    # 🆕 Analytics snapshot updater – runs every 10 minutes
    "compute-analytics-snapshot": {
        "task": "apps.analytics.tasks.compute_and_cache_analytics",
        "schedule": crontab(minute="*/10"),  # every 10 minutes
    },
}

# =============================================================================
# HTTPS / HSTS (only in production)
# =============================================================================
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
