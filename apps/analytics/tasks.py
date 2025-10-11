# apps/analytics/tasks.py
from celery import shared_task
from django.core.cache import cache
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
# careful: only import function-level helpers
from .views import AnalyticsViewSet

CACHE_KEY = "analytics:overview_snapshot"
CACHE_TTL = getattr(settings, "ANALYTICS_CACHE_TTL", 300)  # 5 minutes default


@shared_task
def compute_and_cache_analytics():
    """Compute analytics and store snapshot in cache."""
    try:
        view = AnalyticsViewSet()
        now = timezone.now()
        last_30_days = now - timedelta(days=30)
        last_7_days = now - timedelta(days=7)

        payload = {
            "user_stats": view._get_user_statistics(last_30_days, last_7_days),
            "listing_stats": view._get_listing_statistics(last_30_days, last_7_days),
            "inquiry_stats": view._get_inquiry_statistics(last_30_days, last_7_days),
            "category_stats": view._get_category_statistics(),
            "business_stats": view._get_business_statistics(last_30_days),
            "generated_at": now,
        }
        cache.set(CACHE_KEY, payload, CACHE_TTL)
        return "ok"
    except Exception as exc:
        return str(exc)
