import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hb.settings')
django.setup()

import posthog
from django.conf import settings
from apps.analytics.posthog_utils import capture_event

# Set correct attribute directly
posthog.api_key = settings.POSTHOG_PROJECT_API_KEY
posthog.host = getattr(settings, 'POSTHOG_HOST', 'https://app.posthog.com')

print(f"Testing PostHog with Key: {settings.POSTHOG_PROJECT_API_KEY[:10]}...")
print(f"PostHog api_key set to: {posthog.api_key[:10]}...")

capture_event(
    distinct_id="test_user_123",
    event_name="PostHog Connection Test",
    properties={"status": "working", "environment": "development"}
)

posthog.flush()
print("SUCCESS: Event sent! Check your PostHog dashboard (Activity tab).")