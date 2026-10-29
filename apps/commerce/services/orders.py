from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.commerce.models import Order, OrderActivity
from apps.financials.models import VendorEarning
from apps.financials.services import money, release_earning


class InvalidTransition(ValueError):
    pass


# event -> (from_statuses, to_status)
BASE_TRANSITIONS = {
    "order_cancelled": (
        (Order.Status.DRAFT, Order.Status.PENDING_PAYMENT),
        Order.Status.CANCELLED,
    ),
    "order_confirmed": ((Order.Status.PAID,), Order.Status.ORDER_CONFIRMED),
    "item_dispatched": (
        (Order.Status.PAID, Order.Status.ORDER_CONFIRMED),
        Order.Status.ITEM_DISPATCHED,
    ),
    "in_transit": ((Order.Status.ITEM_DISPATCHED,), Order.Status.IN_TRANSIT),
    "delivered": ((Order.Status.IN_TRANSIT,), Order.Status.DELIVERED),
    "order_fulfilled": ((Order.Status.DELIVERED,), Order.Status.FULFILLED),
    "hire_started": ((Order.Status.DELIVERED,), Order.Status.ACTIVE_HIRE),
    "hire_ended": ((Order.Status.ACTIVE_HIRE,), Order.Status.HIRE_ENDED),
    "item_returned": ((Order.Status.HIRE_ENDED,), Order.Status.ITEM_RETURNED),
}

RENTAL_TYPES = (Order.OrderType.HIRE, Order.OrderType.LEASE)


def _transitions_for(order):
    """The transition table for this order's purchase type."""
    table = dict(BASE_TRANSITIONS)
    has_rental = order.items.filter(purchase_type__in=RENTAL_TYPES).exists()
    if has_rental:
        # A rental is not complete on delivery; it must be returned first.
        table["order_fulfilled"] = (
            (Order.Status.ITEM_RETURNED,),
            Order.Status.FULFILLED,
        )
    else:
        table.pop("hire_started", None)
        table.pop("hire_ended", None)
        table.pop("item_returned", None)
    return table


@transaction.atomic
def transition(order, event, actor=None, **payload):
    """The only function allowed to change ``Order.status``.

    Raises ``InvalidTransition`` for an event the order cannot perform now.
    """
    order = Order.objects.select_for_update().get(pk=order.pk)
    table = _transitions_for(order)
    rule = table.get(event)
    if rule is None:
        raise InvalidTransition(f"Unknown event '{event}'.")

    from_statuses, to_status = rule
    if order.status not in from_statuses:
        raise InvalidTransition(
            f"Cannot '{event}' an order in status '{order.status}'."
        )

    now = timezone.now()
    update_fields = ["status"]

    if event == "item_dispatched":
        carrier = (payload.get("carrier") or "").strip()
        tracking_id = (payload.get("tracking_id") or "").strip()
        if not carrier or not tracking_id:
            raise InvalidTransition("carrier and tracking_id are required.")
        order.delivery_carrier = carrier
        order.tracking_id = tracking_id
        order.shipped_at = now
        update_fields += ["delivery_carrier", "tracking_id", "shipped_at"]

    if event == "delivered":
        order.delivered_at = now
        update_fields.append("delivered_at")

    if event == "order_fulfilled":
        order.completed_at = now
        update_fields.append("completed_at")

    if event == "order_cancelled":
        order.cancelled_at = now
        update_fields.append("cancelled_at")
        reason = payload.get("reason")
        if reason:
            order.cancellation_reason = reason
            update_fields.append("cancellation_reason")

    order.status = to_status
    order.save(update_fields=update_fields)

    OrderActivity.objects.create(
        order=order,
        event_type=event,
        message=payload.get("message") or f"Order moved to {to_status}.",
    )

    if event == "order_fulfilled":
        _release_final_tranche(order)

    return order


def _release_final_tranche(order):
    """Release whatever net amount is still held once the order completes."""
    earning = VendorEarning.objects.filter(order=order).first()
    if earning is None or earning.is_disputed:
        return earning

    remaining = money(earning.net_amount - earning.released_amount)
    if remaining > Decimal("0.00"):
        release_earning(earning, remaining)
    return earning
