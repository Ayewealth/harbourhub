from decimal import Decimal

import pytest

from apps.commerce.models import (
    Dispute,
    Order,
    Payment,
    Refund,
)
from apps.commerce.services.refunds import finalize_refund
from apps.financials.models import VendorEarning

from .factories import (
    DisputeFactory,
    OrderFactory,
    OrderItemFactory,
    PaymentFactory,
    UserFactory,
)


def _paid_order_with_earning():
    order = OrderFactory(
        status=Order.Status.PAID,
        subtotal=Decimal("1000.00"),
        total_amount=Decimal("1000.00"),
    )
    OrderItemFactory(order=order)
    payment = PaymentFactory(
        checkout_session=order.checkout_session,
        buyer=order.buyer,
        amount=Decimal("1000.00"),
        status=Payment.Status.SUCCESS,
    )
    VendorEarning.objects.create(
        order=order,
        vendor=order.seller,
        store=order.store,
        earning_type="buy",
        gross_amount=Decimal("1000.00"),
        commission_rate=Decimal("0.00"),
        commission_amount=Decimal("0.00"),
        net_amount=Decimal("1000.00"),
        status=VendorEarning.Status.AVAILABLE,
        released_amount=Decimal("1000.00"),
    )
    return order, payment


@pytest.mark.django_db
def test_full_refund_moves_an_open_dispute_to_refunded():
    order, payment = _paid_order_with_earning()
    dispute = DisputeFactory(order=order, buyer=order.buyer)
    refund = Refund.objects.create(
        payment=payment,
        amount=Decimal("1000.00"),
        currency="NGN",
        reference="RF-DISPUTE-FULL",
        reason="Item not delivered",
    )

    finalize_refund(refund)

    dispute.refresh_from_db()
    assert dispute.status == Dispute.Status.REFUNDED
    assert dispute.resolved_at is not None
    assert "RF-DISPUTE-FULL" in dispute.resolution_notes


@pytest.mark.django_db
def test_partial_refund_leaves_the_dispute_untouched():
    order, payment = _paid_order_with_earning()
    dispute = DisputeFactory(order=order, buyer=order.buyer)
    refund = Refund.objects.create(
        payment=payment,
        amount=Decimal("400.00"),
        currency="NGN",
        reference="RF-DISPUTE-PARTIAL",
        reason="Partial damage",
    )

    finalize_refund(refund)

    dispute.refresh_from_db()
    assert dispute.status == Dispute.Status.OPEN


@pytest.mark.django_db
def test_buyer_can_cancel_an_open_dispute(auth_client):
    dispute = DisputeFactory()

    response = auth_client(dispute.buyer).post(
        f"/commerce/disputes/{dispute.pk}/cancel/",
        {"resolution_notes": "Resolved directly with the seller."},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["message"] == "Dispute cancelled successfully."
    dispute.refresh_from_db()
    assert dispute.status == Dispute.Status.CANCELLED
    assert dispute.resolved_at is not None
    assert dispute.resolution_notes == "Resolved directly with the seller."


@pytest.mark.django_db
def test_only_the_buyer_can_cancel(auth_client):
    dispute = DisputeFactory()
    other = UserFactory()

    response = auth_client(other).post(
        f"/commerce/disputes/{dispute.pk}/cancel/", {}, format="json"
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_a_resolved_dispute_cannot_be_cancelled(auth_client):
    dispute = DisputeFactory(status=Dispute.Status.RESOLVED)

    response = auth_client(dispute.buyer).post(
        f"/commerce/disputes/{dispute.pk}/cancel/", {}, format="json"
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_admin_can_cancel_a_dispute(auth_client):
    dispute = DisputeFactory()
    admin = UserFactory(role="admin", is_staff=True, is_superuser=True)

    response = auth_client(admin).post(
        f"/commerce/disputes/{dispute.pk}/action/",
        {"action": "cancel"},
        format="json",
    )

    assert response.status_code == 200
    dispute.refresh_from_db()
    assert dispute.status == Dispute.Status.CANCELLED
