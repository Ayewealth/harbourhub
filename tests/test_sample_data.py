"""P3: the sample data command must be opt-in, money-correct, and idempotent."""
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.categories.models import Category
from apps.commerce.models import Order, OrderItem, Payment, QuoteRequest
from apps.financials.models import VendorEarning, VendorWallet, WalletTransaction
from apps.financials.services import money
from apps.inquiries.models import Inquiry
from apps.listings.models import Listing, ListingImage, SavedItem
from apps.notifications.models import Notification
from apps.reviews.models import ListingReview, StoreReview
from apps.store.models import Store

pytestmark = pytest.mark.django_db

SMALL = {"users": 12, "listings": 24, "orders": 12}


def _run(**overrides):
    options = dict(SMALL)
    options.update(overrides)
    call_command("create_sample_data", stdout=StringIO(), **options)


def test_command_refuses_when_seeding_is_disabled(settings):
    settings.SEED_SAMPLE_DATA = False
    with pytest.raises(CommandError):
        call_command("create_sample_data", stdout=StringIO(), users=2)


def test_clean_requires_force(settings):
    settings.SEED_SAMPLE_DATA = True
    with pytest.raises(CommandError):
        call_command("create_sample_data", stdout=StringIO(), clean=True)


def test_seeded_orders_and_earnings_carry_consistent_money(settings):
    settings.SEED_SAMPLE_DATA = True
    _run()

    orders = Order.objects.all()
    assert orders.exists()
    for order in orders:
        assert order.subtotal is not None
        assert order.total_amount == order.subtotal + order.delivery_fee
        assert order.escrow_fee == Decimal("0.00")
        assert order.store_id is not None
        assert order.seller_id == order.store.user_id
        item = order.items.get()
        assert item.original_currency == "NGN"
        assert item.original_unit_price == item.unit_price
        if order.status in (Order.Status.PAID, Order.Status.FULFILLED):
            assert order.commission_amount == money(
                order.subtotal * order.commission_rate / Decimal("100")
            )
        else:
            assert order.commission_amount == Decimal("0.00")

    earnings = VendorEarning.objects.all()
    assert earnings.exists()
    for earning in earnings:
        assert earning.gross_amount == earning.order.total_amount
        assert earning.net_amount == (
            earning.gross_amount - earning.commission_amount
        )
        assert earning.commission_amount == earning.order.commission_amount

    # Wallets hold exactly the net of their store's earnings.
    for wallet in VendorWallet.objects.all():
        earned = sum(
            (e.net_amount for e in earnings.filter(store=wallet.store)),
            Decimal("0.00"),
        )
        assert wallet.pending_balance + wallet.available_balance == earned


def test_second_run_adds_no_duplicates(settings):
    settings.SEED_SAMPLE_DATA = True
    _run()

    def snapshot():
        return {
            "categories": Category.objects.count(),
            "stores": Store.objects.count(),
            "listings": Listing.objects.count(),
            "images": ListingImage.objects.count(),
            "inquiries": Inquiry.objects.count(),
            "quotes": QuoteRequest.objects.count(),
            "saved": SavedItem.objects.count(),
            "orders": Order.objects.count(),
            "items": OrderItem.objects.count(),
            "payments": Payment.objects.count(),
            "earnings": VendorEarning.objects.count(),
            "wallets": VendorWallet.objects.count(),
            "wallet_tx": WalletTransaction.objects.count(),
            "reviews": (
                ListingReview.objects.count() + StoreReview.objects.count()
            ),
            "notifications": Notification.objects.count(),
        }

    first = snapshot()
    _run()
    assert snapshot() == first
