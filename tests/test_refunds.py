import pytest
from rest_framework import status

from apps.commerce.models import Dispute, Payment, Refund
from apps.commerce.services.refunds import finalize_refund, request_refund
from apps.financials.models import VendorEarning
from apps.financials.services import accrue_earning
from tests.factories import OrderFactory, OrderItemFactory, PaymentFactory, UserFactory


@pytest.mark.django_db
def test_non_admin_cannot_refund(auth_client):
    order = OrderFactory()
    dispute = Dispute.objects.create(
        order=order, buyer=order.buyer, reason="broken", description="broken"
    )
    client = auth_client(UserFactory())

    response = client.post(
        f"/commerce/disputes/{dispute.pk}/action/",
        {"action": "refund", "resolution_notes": "give money back"},
        format="json",
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert not Refund.objects.exists()


@pytest.mark.django_db
def test_refund_reverses_earning_and_cancels_order(monkeypatch):
    order = OrderFactory()
    OrderItemFactory(order=order)
    payment = PaymentFactory(
        checkout_session=order.checkout_session,
        amount=order.total_amount,
        status=Payment.Status.SUCCESS,
    )
    earning = accrue_earning(order)

    monkeypatch.setattr(
        "apps.commerce.services.refunds.initiate_refund",
        lambda *args, **kwargs: {"reference": "RF-1", "status": "pending"},
    )
    refund = request_refund(
        payment, payment.amount, "damaged", actor=order.buyer
    )
    finalize_refund(refund, {"reference": "RF-1"})

    refund.refresh_from_db()
    payment.refresh_from_db()
    order.refresh_from_db()
    earning.refresh_from_db()
    assert refund.status == Refund.Status.PROCESSED
    assert payment.status == Payment.Status.REFUNDED
    assert order.status == "cancelled"
    assert earning.status == VendorEarning.Status.REVERSED
