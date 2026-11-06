"""Single source of truth for public listing visibility.

Every public surface must use these helpers so the enabled-type and published rules
cannot drift between the listing list, detail, recommendations, search, stores and
category counts.
"""
from django.db.models import Q

from apps.admin_panel.models import PlatformConfig

from .models import Listing

TYPE_FLAGS = {
    Listing.Type.SELL: "enable_buy",
    Listing.Type.RENT: "enable_rent",
    Listing.Type.LEASE: "enable_rent",
    Listing.Type.SERVICE: "enable_services",
}

DISABLED_TYPE_MESSAGES = {
    Listing.Type.SELL: "Buy listings are currently disabled.",
    Listing.Type.RENT: "Rent and lease listings are currently disabled.",
    Listing.Type.LEASE: "Rent and lease listings are currently disabled.",
    Listing.Type.SERVICE: "Service listings are currently disabled.",
}

OWNER_SETTABLE_STATUSES = {
    Listing.Status.DRAFT,
    Listing.Status.PUBLISHED,
    Listing.Status.PAUSED,
    Listing.Status.ARCHIVED,
}

APPROVAL_REQUIRED_ERROR = (
    "Listings require admin approval before publishing."
)


def get_platform_config():
    """Return the singleton config, creating defaults on first read."""
    return PlatformConfig.get()


def is_admin(user):
    return bool(
        user
        and user.is_authenticated
        and (user.is_staff or user.is_superuser or user.is_admin_user)
    )


def enabled_listing_types(config=None):
    config = config or get_platform_config()
    return [
        listing_type
        for listing_type, flag in TYPE_FLAGS.items()
        if getattr(config, flag)
    ]


def enabled_types_q(prefix=""):
    """Q object restricting a queryset to enabled listing types."""
    return Q(**{f"{prefix}listing_type__in": enabled_listing_types()})


def public_listing_q():
    """Published, active-store, enabled-type."""
    return (
        Q(status=Listing.Status.PUBLISHED)
        & Q(store__is_active=True)
        & enabled_types_q()
    )


def public_listings(queryset=None):
    queryset = queryset if queryset is not None else Listing.objects.all()
    return queryset.filter(public_listing_q())


def validate_listing_type_enabled(listing_type, config=None):
    """Return an error string when the type is disabled, else None."""
    config = config or get_platform_config()
    flag = TYPE_FLAGS.get(listing_type)
    if flag and not getattr(config, flag):
        return DISABLED_TYPE_MESSAGES[listing_type]
    return None


def can_publish(listing, user, config=None):
    """Approval rule shared by the serializer and the publish action."""
    if is_admin(user):
        return True
    config = config or get_platform_config()
    if not config.listing_approval_required:
        return True
    return listing.published_at is not None
