from .models import Order

# States in which money has been captured and the sale is still real.
# CANCELLED is excluded. DRAFT/PENDING_PAYMENT are excluded.
SALES_STATUSES = [
    Order.Status.PAID,
    Order.Status.ORDER_CONFIRMED,
    Order.Status.ITEM_DISPATCHED,
    Order.Status.IN_TRANSIT,
    Order.Status.DELIVERED,
    Order.Status.ACTIVE_HIRE,
    Order.Status.HIRE_ENDED,
    Order.Status.ITEM_RETURNED,
    Order.Status.FULFILLED,
]

# States in which the rental clock is still running.
ACTIVE_RENTAL_STATUSES = [
    Order.Status.PAID,
    Order.Status.ORDER_CONFIRMED,
    Order.Status.ITEM_DISPATCHED,
    Order.Status.IN_TRANSIT,
    Order.Status.DELIVERED,
    Order.Status.ACTIVE_HIRE,
]

# States that still block deleting the listing behind them. FULFILLED is
# terminal, so it is allowed to drop out of the guard.
LIVE_ORDER_STATUSES = [
    Order.Status.PENDING_PAYMENT,
    Order.Status.PAID,
    Order.Status.ORDER_CONFIRMED,
    Order.Status.ITEM_DISPATCHED,
    Order.Status.IN_TRANSIT,
    Order.Status.DELIVERED,
    Order.Status.ACTIVE_HIRE,
    Order.Status.HIRE_ENDED,
    Order.Status.ITEM_RETURNED,
]
