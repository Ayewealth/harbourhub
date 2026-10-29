from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.commerce.models import Order, RentalExtension
from apps.commerce.services.payments import finalize_payment
from apps.financials.models import VendorEarning

from .factories import OrderFactory, OrderItemFactory, PaymentFactory


def _hire_order(**kwargs):
    today = timezone.now().date()
    order = OrderFactory(status=Order.Status.ACTIVE_HIRE, **kwargs)
    item = OrderItemFactory(
        order=order,
        purchase_type=Order.OrderType.HIRE,
        unit_price=Decimal("1000.00"),
        quantity=1,
        duration_days=7,
        rental_start_date=today - timedelta(days=2),
        rental_end_date=today + timedelta(days=5),
    )
    return order, item


@pytest.mark.django_db
def test_extension_does_not_change_dates_until_payment(auth_client):
    order, item = _hire_order()
    previous_end = item.rental_end_date
    client = auth_client(order.buyer)

    with patch("apps.commerce.views.initialize_transaction") as gateway:
        gateway.return_value = {
            "authorization_url": "https://pay.test/x",
            "access_code": "abc",
        }
        response = client.post(
            f"/commerce/orders/{order.id}/items/{item.id}/extend-rental/",
            {"duration_days": 3},
            format="json",
        )

    assert response.status_code == 201
    assert response.data["amount"] == "3000.00"
    item.refresh_from_db()
    extension = RentalExtension.objects.get(order_item=item)
    assert extension.status == RentalExtension.Status.PENDING_PAYMENT
    assert item.rental_end_date == previous_end
    assert extension.payment_id is not None


@pytest.mark.django_db
def test_gateway_failure_cancels_the_extension(auth_client):
    order, item = _hire_order()
    previous_end = item.rental_end_date

    with patch("apps.commerce.views.initialize_transaction") as gateway:
        gateway.return_value = None
        response = auth_client(order.buyer).post(
            f"/commerce/orders/{order.id}/items/{item.id}/extend-rental/",
            {"duration_days": 3},
            format="json",
        )

    assert response.status_code == 502
    item.refresh_from_db()
    assert item.rental_end_date == previous_end
    extension = RentalExtension.objects.get(order_item=item)
    assert extension.status == RentalExtension.Status.CANCELLED
    assert extension.payment.status == "failed"


@pytest.mark.django_db
def test_extension_is_rejected_for_a_non_rental_item(auth_client):
    order = OrderFactory(status=Order.Status.PAID)
    item = OrderItemFactory(order=order, purchase_type=Order.OrderType.BUY)

    response = auth_client(order.buyer).post(
        f"/commerce/orders/{order.id}/items/{item.id}/extend-rental/",
        {"duration_days": 3},
        format="json",
    )

    assert response.status_code == 404
    assert not RentalExtension.objects.exists()


@pytest.mark.django_db
def test_extension_rejects_a_shorter_end_date(auth_client):
    order, item = _hire_order()

    response = auth_client(order.buyer).post(
        f"/commerce/orders/{order.id}/items/{item.id}/extend-rental/",
        {"new_end_date": str(timezone.now().date())},
        format="json",
    )

    assert response.status_code == 400
    assert not RentalExtension.objects.exists()


@pytest.mark.django_db
def test_payment_applies_the_extension_once():
    order, item = _hire_order()
    previous_end = item.rental_end_date
    extension = RentalExtension.objects.create(
        order_item=item,
        additional_days=3,
        previous_end_date=previous_end,
        new_end_date=previous_end + timedelta(days=3),
        amount=Decimal("3000.00"),
    )
    payment = PaymentFactory(
        buyer=order.buyer,
        amount=Decimal("3000.00"),
        checkout_session=None,
    )
    extension.payment = payment
    extension.save(update_fields=["payment"])

    finalize_payment(payment, {"amount": 300000})
    finalize_payment(payment, {"amount": 300000})

    item.refresh_from_db()
    extension.refresh_from_db()
    order.refresh_from_db()
    assert item.rental_end_date == previous_end + timedelta(days=3)
    assert item.duration_days == 10
    assert extension.status == RentalExtension.Status.PAID
    assert order.subtotal == Decimal("4000.00")
    assert order.total_amount == Decimal("4000.00")


@pytest.mark.django_db
def test_extension_payment_credits_the_vendor_and_keeps_commission():
    order, item = _hire_order()
    earning = VendorEarning.objects.create(
        order=order,
        vendor=order.seller,
        store=order.store,
        earning_type="rent",
        gross_amount=Decimal("1000.00"),
        commission_rate=Decimal("5.00"),
        commission_amount=Decimal("50.00"),
        net_amount=Decimal("950.00"),
    )
    previous_end = item.rental_end_date
    extension = RentalExtension.objects.create(
        order_item=item,
        additional_days=3,
        previous_end_date=previous_end,
        new_end_date=previous_end + timedelta(days=3),
        amount=Decimal("3000.00"),
    )
    payment = PaymentFactory(
        buyer=order.buyer,
        amount=Decimal("3000.00"),
        checkout_session=None,
    )
    extension.payment = payment
    extension.save(update_fields=["payment"])

    finalize_payment(payment, {"amount": 300000})

    earning.refresh_from_db()
    assert earning.gross_amount == Decimal("4000.00")
    assert earning.commission_amount == Decimal("200.00")
    assert earning.net_amount == Decimal("3800.00")


@pytest.mark.django_db
def test_legacy_endpoint_points_at_the_item_endpoint(auth_client):
    order, item = _hire_order()

    response = auth_client(order.buyer).post(
        f"/commerce/orders/{order.id}/extend-rental/",
        {"duration_days": 3},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["item_id"] == item.id
    assert (
        f"/commerce/orders/{order.id}/items/{item.id}/extend-rental/"
        == response.data["endpoint"]
    )
    item.refresh_from_db()
    assert not RentalExtension.objects.exists()
