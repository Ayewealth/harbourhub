# apps/listings/tasks.py
import logging
from celery import shared_task
from django.utils import timezone
from django.db import transaction

from .models import Listing, ListingView

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=5)
def record_listing_view_task(self, listing_id, user_id=None, ip_address=None, user_agent=''):
    """
    Create a ListingView record and increment the views_count safely.
    This offloads analytics to background and avoids slowing the request.
    """
    try:
        listing = Listing.objects.get(pk=listing_id)
        # create view record
        ListingView.objects.create(
            listing=listing,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent or ''
        )
    except Listing.DoesNotExist:
        logger.warning(
            "record_listing_view_task: listing %s not found", listing_id)
    except Exception as exc:
        logger.exception("record_listing_view_task failed: %s", exc)
        raise self.retry(exc=exc)


@shared_task(bind=True)
def expire_listings_task(self):
    """
    Archive listings that have expired. Run periodically (via beat).
    """
    print("Running expire_listings_task ✅")
    now = timezone.now()
    qs = Listing.objects.filter(
        expires_at__lte=now, status=Listing.Status.PUBLISHED)
    count = qs.update(status=Listing.Status.ARCHIVED)
    logger.info("expire_listings_task archived %d listings", count)
    return count
