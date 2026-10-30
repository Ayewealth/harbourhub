"""P3: list endpoints must not run one query per row (N+1)."""
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.commerce.models import Order

from .factories import (
    DisputeFactory,
    ListingFactory,
    OrderFactory,
    OrderItemFactory,
    QuoteRequestFactory,
    StoreFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


def _queries(client, url):
    with CaptureQueriesContext(connection) as context:
        response = client.get(url)
    assert response.status_code == 200, response.data
    return [query["sql"] for query in context.captured_queries]


def _assert_constant_queries(client, url, create_more):
    """Query count must not grow when more rows are added to the page."""
    create_more()
    # First request warms per-user caches (e.g. UserPreference) that the shared
    # authenticated user instance keeps between calls.
    _queries(client, url)
    baseline = _queries(client, url)
    for _ in range(4):
        create_more()
    after = _queries(client, url)
    assert len(after) == len(baseline), "\n".join(after)


def test_order_list_query_count_is_flat(auth_client):
    buyer = UserFactory()
    store = StoreFactory()
    client = auth_client(buyer)

    def create_more():
        order = OrderFactory(buyer=buyer, store=store)
        OrderItemFactory(order=order)

    create_more()
    _assert_constant_queries(client, "/commerce/orders/", create_more)


def test_recent_sales_query_count_is_flat(auth_client):
    store = StoreFactory()
    client = auth_client(store.user)

    def create_more():
        order = OrderFactory(
            store=store,
            seller=store.user,
            status=Order.Status.PAID,
        )
        OrderItemFactory(order=order)

    create_more()
    _assert_constant_queries(client, "/commerce/orders/recent-sales/", create_more)


def test_sent_quotes_query_count_is_flat(auth_client):
    buyer = UserFactory()
    listing = ListingFactory()
    client = auth_client(buyer)

    def create_more():
        QuoteRequestFactory(listing=listing, buyer=buyer)

    create_more()
    _assert_constant_queries(client, "/commerce/quotes/sent/", create_more)


def test_received_quotes_query_count_is_flat(auth_client):
    listing = ListingFactory()
    client = auth_client(listing.store.user)

    def create_more():
        QuoteRequestFactory(listing=listing)

    create_more()
    _assert_constant_queries(client, "/commerce/quotes/received/", create_more)


def test_dispute_list_query_count_is_flat(auth_client):
    buyer = UserFactory()
    client = auth_client(buyer)

    def create_more():
        order = OrderFactory(buyer=buyer)
        DisputeFactory(order=order, buyer=buyer)

    create_more()
    _assert_constant_queries(client, "/commerce/disputes/", create_more)

