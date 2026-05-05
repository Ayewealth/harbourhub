from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"

    def ready(self):
        from django.conf import settings
        import posthog

        posthog.api_key = settings.POSTHOG_PROJECT_API_KEY
        posthog.host = settings.POSTHOG_HOST
