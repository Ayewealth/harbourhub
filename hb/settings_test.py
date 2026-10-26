"""Settings for the automated test suite.

Import order matters: settings.py reads .env, so the test module must import it
first and then override anything that would reach a real service.
"""
import tempfile

from .settings import *  # noqa: F401,F403

DEBUG = False

# Database -------------------------------------------------------------------
# Use the same engine as production. CI supplies a PostgreSQL service; locally
# the developer's PostgreSQL server is used. The name is isolated from dev data.
DATABASES["default"]["TEST"] = {"NAME": "test_harbour_hub"}  # noqa: F405

# Celery ---------------------------------------------------------------------
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"

# Mail -----------------------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Storage --------------------------------------------------------------------
USE_S3 = False
MEDIA_ROOT = tempfile.mkdtemp(prefix="harbour-hub-test-media-")
MEDIA_URL = "/media/"

# Speed ----------------------------------------------------------------------
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# External services ----------------------------------------------------------
RATELIMIT_ENABLE = False
SENTRY_DSN = None
PAYSTACK_SECRET_KEY = "sk_test_p0_harness"

# Cache ----------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "harbour-hub-tests",
    }
}
