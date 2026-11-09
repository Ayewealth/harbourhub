import csv
import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.commerce.models import Dispute, Order
from apps.inquiries.models import Inquiry
from apps.listings.models import Listing

from .factories import (
    DisputeFactory,
    ListingFactory,
    OrderFactory,
    UserFactory,
)


def _admin():
    return UserFactory(role="admin", is_staff=True, is_superuser=True)


def _read_csv(response):
    return list(csv.DictReader(io.StringIO(response.content.decode())))


@pytest.mark.django_db
def test_export_returns_real_metrics(auth_client):
    OrderFactory(
        status=Order.Status.FULFILLED,
        total_amount=Decimal("1500.00"),
        placed_at=timezone.now(),
    )
    DisputeFactory(status=Dispute.Status.OPEN)
    listing = ListingFactory(
        status=Listing.Status.PUBLISHED, published_at=timezone.now()
    )
    Inquiry.objects.create(
        listing=listing,
        from_user=UserFactory(),
        to_user=listing.user,
        subject="Availability",
        message="Is this available?",
        contact_name="Ada Obi",
        contact_email="ada@example.com",
    )
    UserFactory()

    response = auth_client(_admin()).get("/admin-panel/analytics/export/")

    assert response.status_code == 200
    rows = {row["Metric"]: row["Value"] for row in _read_csv(response)}
    assert Decimal(rows["Total Revenue"]) == Decimal("1500.00")
    assert int(rows["Paid Orders"]) >= 1
    assert int(rows["Active Disputes"]) >= 1
    assert int(rows["New Inquiries"]) >= 1
    assert int(rows["New Users"]) >= 1
    assert int(rows["Active Listings"]) >= 1


@pytest.mark.django_db
def test_export_rejects_an_invalid_date(auth_client):
    response = auth_client(_admin()).get(
        "/admin-panel/analytics/export/?date_from=not-a-date"
    )

    assert response.status_code == 400
    assert response.data["error"] == "Invalid date format. Use YYYY-MM-DD."
