import logging
import uuid
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.financials.services import money, reverse_earning_amount

from ..models import Order, OrderActivity, Payment, Refund
from ..paystack import initiate_refund

logger = logging.getLogger(__name__)


class RefundError(ValueError):
    pass


def request_refund(payment: Payment, amount, reason: str, actor) -> Refund:
    amount = money(amount)
    if amount <= 0:
        raise RefundError("Refund amount must be greater than zero.")
    if amount > payment.amount:
        raise RefundError("Refund amount exceeds payment amount.")
    if payment.status != Payment.Status.SUCCESS:
        raise RefundError("Only successful payments can be refunded.")

    data = initiate_refund(
        payment.reference,
        amount_kobo=int(amount * 100),
        reason=reason,
    )
    if data is None:
        raise RefundError("The payment gateway rejected the refund request.")

    refund = Refund.objects.create(
        payment=payment,
        amount=amount,
        currency=payment.currency,
        reason=reason,
        reference=data.get("reference") or f"RF-{uuid.uuid4().hex[:12].upper()}",
        gateway_response=data,
        requested_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    return refund


@transaction.atomic
def finalize_refund(refund: Refund, payload: dict | None = None):
    """Apply a gateway-confirmed refund exactly once, proportionally."""
    from apps.financials.models import VendorEarning

    refund = Refund.objects.select_for_update().get(pk=refund.pk)
    if refund.status == Refund.Status.PROCESSED:
        return refund

    payment = Payment.objects.select_for_update().get(pk=refund.payment_id)
    refund.status = Refund.Status.PROCESSED
    refund.processed_at = timezone.now()
    if payload:
        refund.gateway_response = payload
    refund.save(update_fields=["status", "processed_at", "gateway_response"])

    full_refund = refund.amount >= payment.amount
    payment.status = (
        Payment.Status.REFUNDED
        if full_refund
        else Payment.Status.PARTIALLY_REFUNDED
    )
    payment.save(update_fields=["status"])

    ratio = (
        Decimal("1")
        if payment.amount == 0
        else (refund.amount / payment.amount)
    )

    if payment.checkout_session_id:
        for order in payment.checkout_session.orders.select_for_update():
            earning = VendorEarning.objects.filter(order=order).first()
            if earning is not None:
                reverse_earning_amount(
                    earning,
                    money(earning.net_amount * ratio),
                    f"Refund {refund.reference} for order {order.order_number}",
                )

            if not full_refund:
                continue

            order.status = Order.Status.CANCELLED
            order.cancelled_at = timezone.now()
            order.cancellation_reason = refund.reason
            order.save(
                update_fields=[
                    "status", "cancelled_at", "cancellation_reason"
                ]
            )
            OrderActivity.objects.create(
                order=order,
                event_type=OrderActivity.EventType.ORDER_REFUNDED,
                message=f"Refunded: {refund.reason}",
            )

    return refund
