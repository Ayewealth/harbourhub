import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.financials.services import accrue_earning, money
from apps.notifications.utils import notify_order_paid

from ..models import Order, OrderActivity, Payment

logger = logging.getLogger(__name__)


class PaymentAmountMismatch(ValueError):
    pass


def _normalise_payload(payload: dict) -> dict:
    if isinstance(payload, dict) and "data" in payload and isinstance(payload["data"], dict):
        return payload["data"]
    return payload or {}


@transaction.atomic
def finalize_payment(payment, gateway_payload: dict):
    """The only function allowed to mark a payment successful.

    Returns True when this call performed the transition, False when the payment
    was already successful.
    """
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status == Payment.Status.SUCCESS:
        return False

    payload = _normalise_payload(gateway_payload)
    gateway_amount = payload.get("amount")
    if gateway_amount not in (None, 0, "0"):
        expected = int(money(payment.amount) * 100)
        if int(gateway_amount) != expected:
            raise PaymentAmountMismatch(
                f"Gateway amount {gateway_amount} != expected {expected} "
                f"for {payment.reference}"
            )

    payment.status = Payment.Status.SUCCESS
    payment.paid_at = timezone.now()
    payment.gateway_response = gateway_payload or {}
    payment.save(update_fields=["status", "paid_at", "gateway_response"])

    checkout_session = payment.checkout_session
    if checkout_session:
        for order in checkout_session.orders.select_for_update():
            if order.status != Order.Status.PENDING_PAYMENT:
                continue

            # Snapshot the commission now: the store rate may change later and
            # must never rewrite the history of a completed sale.
            rate = order.store.commission_rate
            order.commission_rate = rate
            order.commission_amount = money(
                (order.subtotal or Decimal("0.00")) * rate / Decimal("100")
            )
            order.status = Order.Status.PAID
            order.save(
                update_fields=[
                    "status",
                    "commission_rate",
                    "commission_amount",
                ]
            )

            transaction.on_commit(
                lambda order=order: notify_order_paid(order))
            OrderActivity.objects.create(
                order=order,
                event_type=OrderActivity.EventType.PAYMENT_CONFIRMED,
                message="Payment confirmed.",
            )
            accrue_earning(order)

    return True
