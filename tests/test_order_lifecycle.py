from datetime import timedelta

import pytest
from django.utils import timezone

from apps.commerce.models import Order

from .factories import OrderFactory, OrderItemFactory


@pytest.mark.django_db
def test_extend_rental_updates_items_and_returns_legacy_shape(auth_client):
    today = timezone.now().date()
    order = OrderFactory(status=Order.Status.ACTIVE_HIRE)
    item = OrderItemFactory(
        order=order,
        purchase_type=Order.OrderType.HIRE,
        rental_start_date=today - timedelta(days=5),
        rental_end_date=today + timedelta(days=2),
        duration_days=7,
    )
    client = auth_client(order.buyer)

    response = client.post(
        f"/commerce/orders/{order.id}/extend-rental/",
        {"duration_days": 7},
        format="json",
    )

    assert response.status_code == 200
    item.refresh_from_db()
    assert item.rental_end_date == today + timedelta(days=9)
    assert item.duration_days == 14
    assert response.data["new_end_date"] == str(today + timedelta(days=9))
    assert response.data["rental_days_total"] == 14


@pytest.mark.django_db
def test_extend_rental_rejects_a_shorter_date(auth_client):
    today = timezone.now().date()
    order = OrderFactory(status=Order.Status.ACTIVE_HIRE)
    OrderItemFactory(
        order=order,
        purchase_type=Order.OrderType.HIRE,
        rental_start_date=today - timedelta(days=5),
        rental_end_date=today + timedelta(days=2),
        duration_days=7,
    )
    client = auth_client(order.buyer)

    response = client.post(
        f"/commerce/orders/{order.id}/extend-rental/",
        {"new_end_date": str(today)},
        format="json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_extend_rental_rejects_a_non_rental_order(auth_client):
    order = OrderFactory(status=Order.Status.PAID)
    OrderItemFactory(order=order, purchase_type=Order.OrderType.BUY)
    client = auth_client(order.buyer)

    response = client.post(
        f"/commerce/orders/{order.id}/extend-rental/",
        {"duration_days": 7},
        format="json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_ship_requires_carrier_and_tracking(auth_client):
    order = OrderFactory(status=Order.Status.PAID)
    OrderItemFactory(order=order)
    client = auth_client(order.seller)

    response = client.post(
        f"/commerce/orders/{order.id}/ship/", {}, format="json"
    )

    assert response.status_code == 400
    order.refresh_from_db()
    assert order.status == Order.Status.PAID


@pytest.mark.django_db
def test_ship_records_tracking_and_dispatches(auth_client):
    order = OrderFactory(status=Order.Status.PAID)
    OrderItemFactory(order=order)
    client = auth_client(order.seller)

    response = client.post(
        f"/commerce/orders/{order.id}/ship/",
        {"carrier": "GIG Logistics", "tracking_id": "GIG-123"},
        format="json",
    )

    assert response.status_code == 200
    order.refresh_from_db()
    assert order.status == Order.Status.ITEM_DISPATCHED
    assert order.delivery_carrier == "GIG Logistics"
    assert order.tracking_id == "GIG-123"
    assert order.activities.filter(event_type="shipped").exists()
