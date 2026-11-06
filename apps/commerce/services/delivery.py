"""Delivery fee resolution from a seller's active shipping profiles."""
from decimal import Decimal

from apps.financials.services import money
from apps.listings.models import Listing

ZERO = Decimal("0.00")


def _match_profile(profiles, address):
    """Match city, then state, then country; first hit wins."""
    for part in (address.city, address.state, address.country):
        needle = (part or "").strip().lower()
        if not needle:
            continue
        matches = [
            profile
            for profile in profiles
            if (profile.zone_name or "").strip().lower() == needle
        ]
        if matches:
            return sorted(
                matches, key=lambda profile: (profile.flat_rate_cost, profile.pk)
            )[0]
    return None


def calculate_delivery_fee(cart_item, subtotal_ngn):
    """Return the NGN delivery fee for one cart line.

    Rules: services and missing addresses are free; a matching active zone
    charges its flat rate once per line; no match is free; a reached
    free-shipping threshold is free.
    """
    listing = cart_item.listing
    if listing.listing_type == Listing.Type.SERVICE:
        return ZERO

    address = cart_item.delivery_detail
    if address is None:
        return ZERO

    profiles = list(listing.store.shipping_profiles.filter(is_active=True))
    profile = _match_profile(profiles, address)
    if profile is None:
        return ZERO

    threshold = profile.free_shipping_threshold
    if threshold is not None and subtotal_ngn >= threshold:
        return ZERO

    return money(profile.flat_rate_cost)
