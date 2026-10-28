import pytest

from apps.commerce.models import Order

from .factories import ListingFactory, OrderFactory, OrderItemFactory


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status",
    [
        Order.Status.PAID,
        Order.Status.ORDER_CONFIRMED,
        Order.Status.ITEM_DISPATCHED,
        Order.Status.IN_TRANSIT,
        Order.Status.DELIVERED,
        Order.Status.ACTIVE_HIRE,
        Order.Status.HIRE_ENDED,
        Order.Status.ITEM_RETURNED,
        Order.Status.FULFILLED,
    ],
)
def test_sales_count_includes_every_paid_state(status):
    listing = ListingFactory()
    OrderFactory(store=listing.store, status=status)

    assert listing.store.sales_count == 1


@pytest.mark.django_db
def test_sales_count_ignores_unpaid_and_cancelled():
    listing = ListingFactory()
    OrderFactory(store=listing.store, status=Order.Status.PENDING_PAYMENT)
    OrderFactory(store=listing.store, status=Order.Status.CANCELLED)

    assert listing.store.sales_count == 0


@pytest.mark.django_db
def test_recent_sales_survives_shipping(auth_client):
    listing = ListingFactory()
    order = OrderFactory(
        store=listing.store,
        seller=listing.store.user,
        status=Order.Status.ITEM_DISPATCHED,
    )
    OrderItemFactory(order=order, listing=listing)
    client = auth_client(listing.store.user)

    response = client.get("/commerce/orders/recent-sales/")

    assert [row["id"] for row in response.data["results"]] == [order.id]
