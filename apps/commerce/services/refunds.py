import logging
import uuid

from django.db import transaction
from django.utils import timezone

from apps.financials.services import money, reverse_earning

from ..models import Order, Payment, Refund
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
    """Apply a gateway-confirmed refund exactly once."""
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

    payment.status = (
        Payment.Status.REFUNDED
        if refund.amount >= payment.amount
        else Payment.Status.PARTIALLY_REFUNDED
    )
    payment.save(update_fields=["status"])

    if payment.checkout_session_id:
        for order in payment.checkout_session.orders.select_for_update():
            order.status = Order.Status.CANCELLED
            order.save(update_fields=["status"])
            earning = VendorEarning.objects.filter(order=order).first()
            if earning:
                reverse_earning(
                    earning,
                    f"Refund {refund.reference} for order {order.order_number}",
                )

    return refund
