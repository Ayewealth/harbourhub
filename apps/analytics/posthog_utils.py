import logging
from django.conf import settings
import posthog

logger = logging.getLogger(__name__)

def is_tracking_enabled():
    """
    Check if tracking should be executed.
    Disable tracking during tests.
    """
    if getattr(settings, 'TESTING', False):
        return False
    if not getattr(settings, 'POSTHOG_PROJECT_API_KEY', None):
        return False
    return True

def _init_posthog():
    """Initialize PostHog with correct attribute name."""
    posthog.api_key = settings.POSTHOG_PROJECT_API_KEY
    posthog.host = getattr(
        settings, 'POSTHOG_HOST', 'https://app.posthog.com')

def capture_event(distinct_id, event_name, properties=None):
    if not is_tracking_enabled() or not distinct_id:
        return

    try:
        _init_posthog()
        posthog.capture(
            distinct_id=str(distinct_id),
            event=event_name,
            properties=properties or {}
        )
    except Exception as e:
        logger.error(
            f"PostHog capture failed for event {event_name}: {str(e)}")

# ==========================================
# AUTH & ONBOARDING EVENTS
# ==========================================

def track_user_registered(user, signup_method="email"):
    capture_event(
        distinct_id=user.id,
        event_name="User Registered",
        properties={
            "role": user.role,
            "signup_method": signup_method,
            "email": user.email,
        }
    )

def track_user_login(user):
    capture_event(
        distinct_id=user.id,
        event_name="User Logged In",
        properties={
            "role": user.role,
            "is_verified": user.is_verified,
        }
    )

def track_password_reset_requested(email):
    # Using email as distinct_id since user might not be resolved yet
    capture_event(
        distinct_id=email,
        event_name="Password Reset Requested",
        properties={"email": email}
    )

def track_verification_submitted(user, company_name):
    capture_event(
        distinct_id=user.id,
        event_name="Verification Request Submitted",
        properties={
            "company_name": company_name,
            "role": user.role
        }
    )

def track_profile_updated(user, fields_updated):
    capture_event(
        distinct_id=user.id,
        event_name="User Profile Updated",
        properties={
            "fields": fields_updated,
        }
    )

# ==========================================
# STORE EVENTS
# ==========================================

def track_store_created(user, store_id, store_name):
    capture_event(
        distinct_id=user.id,
        event_name="Store Created",
        properties={
            "store_id": store_id,
            "store_name": store_name,
        }
    )

# ==========================================
# LISTINGS EVENTS
# ==========================================

def track_listing_created(user, listing):
    capture_event(
        distinct_id=user.id,
        event_name="Listing Created",
        properties={
            "listing_id": listing.id,
            "listing_type": listing.listing_type,
            "category_id": listing.category_id if listing.category else None,
        }
    )

def track_listing_deleted(user, listing_id, title):
    capture_event(
        distinct_id=user.id,
        event_name="Listing Deleted",
        properties={
            "listing_id": listing_id,
            "title": title,
        }
    )

def track_listing_viewed(user, listing):
    # If user is anonymous, we'd need session id, but for now we fallback to 'anonymous'
    distinct_id = user.id if user and user.is_authenticated else "anonymous"
    capture_event(
        distinct_id=distinct_id,
        event_name="Listing Viewed",
        properties={
            "listing_id": listing.id,
            "price": float(listing.price) if listing.price else None,
            "listing_type": listing.listing_type,
        }
    )

def track_search_performed(user, query_params, results_count):
    distinct_id = user.id if user and user.is_authenticated else "anonymous"
    capture_event(
        distinct_id=distinct_id,
        event_name="Listing Search Performed",
        properties={
            "search_term": query_params.get("search", ""),
            "category": query_params.get("category", ""),
            "results_count": results_count,
        }
    )

# ==========================================
# INQUIRIES EVENTS
# ==========================================

def track_inquiry_sent(user, inquiry):
    distinct_id = user.id if user and user.is_authenticated else inquiry.contact_email
    capture_event(
        distinct_id=distinct_id,
        event_name="Inquiry Sent",
        properties={
            "inquiry_id": inquiry.id,
            "listing_id": inquiry.listing_id if inquiry.listing else None,
            "vendor_id": inquiry.to_user_id if inquiry.to_user else None,
            "is_urgent": inquiry.is_urgent,
        }
    )

def track_inquiry_replied(user, inquiry_reply):
    capture_event(
        distinct_id=user.id,
        event_name="Inquiry Replied",
        properties={
            "inquiry_id": inquiry_reply.inquiry_id,
            "reply_id": inquiry_reply.id,
        }
    )

# ==========================================
# COMMERCE EVENTS
# ==========================================

def track_quote_requested(user, quote):
    distinct_id = user.id if user and user.is_authenticated else "anonymous"
    capture_event(
        distinct_id=distinct_id,
        event_name="Quote Requested",
        properties={
            "quote_id": quote.id,
            "listing_id": quote.listing_id if quote.listing else None,
            "quantity": quote.quantity,
        }
    )

def track_item_added_to_cart(user, listing, quantity):
    capture_event(
        distinct_id=user.id,
        event_name="Item Added to Cart",
        properties={
            "listing_id": listing.id,
            "title": listing.title,
            "quantity": quantity,
            "price": float(listing.price) if listing.price else 0,
        }
    )

def track_order_placed(user, order):
    capture_event(
        distinct_id=user.id,
        event_name="Order Placed",
        properties={
            "order_id": order.id,
            "order_number": order.order_number,
            "total_amount": float(order.total_amount),
            "currency": order.currency,
        }
    )

def track_payment_success(user, order, gateway="paystack"):
    capture_event(
        distinct_id=user.id,
        event_name="Payment Successful",
        properties={
            "order_id": order.id,
            "order_number": order.order_number,
            "total_amount": float(order.total_amount),
            "currency": order.currency,
            "gateway": gateway,
        }
    )

def track_payment_failed(user, order, failure_reason):
    capture_event(
        distinct_id=user.id,
        event_name="Payment Failed",
        properties={
            "order_id": order.id,
            "order_number": order.order_number,
            "total_amount": float(order.total_amount),
            "failure_reason": failure_reason,
        }
    )

# ==========================================
# REVIEW EVENTS
# ==========================================

def track_review_submitted(user, target_type, target_id, rating):
    """
    target_type: 'listing' or 'store'
    """
    capture_event(
        distinct_id=user.id,
        event_name="Review Submitted",
        properties={
            "target_type": target_type,
            "target_id": target_id,
            "rating": rating,
        }
    )
