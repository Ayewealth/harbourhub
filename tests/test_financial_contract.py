from decimal import Decimal

import pytest

from apps.financials.models import VendorWallet
from apps.financials.serializers import EarningsSummarySerializer

from .factories import StoreFactory


@pytest.mark.django_db
def test_earnings_summary_declares_only_returned_fields(auth_client):
    store = StoreFactory()
    wallet, _ = VendorWallet.objects.get_or_create(
        store=store,
        defaults={"user": store.user, "currency": "NGN"},
    )
    wallet.available_balance = Decimal("250.00")
    wallet.total_withdrawn = Decimal("100.00")
    wallet.save(update_fields=["available_balance", "total_withdrawn"])

    response = auth_client(store.user).get("/financials/earnings/summary/")

    assert response.status_code == 200
    assert set(response.data) == {
        "total_revenue",
        "pending_balance",
        "available_balance",
        "total_withdrawn",
        "revenue_change_percent",
        "currency",
    }
    declared = set(EarningsSummarySerializer().fields)
    assert declared == set(response.data)


@pytest.mark.django_db
def test_quote_action_messages_are_grammatical(auth_client):
    from .factories import QuoteRequestFactory

    quote = QuoteRequestFactory()
    response = auth_client(quote.buyer).post(
        f"/commerce/quotes/{quote.pk}/cancel/", {}, format="json"
    )

    assert response.status_code == 200
    assert response.data["message"] == "Quote cancelled successfully"
