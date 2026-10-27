from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from apps.commerce.models import Order
from tests.factories import OrderFactory


@pytest.mark.django_db
def test_command_zeroes_unpaid_buyer_fee_only():
    order = OrderFactory(
        escrow_fee=Decimal("50.00"),
        subtotal=Decimal("1000.00"),
        total_amount=Decimal("1050.00"),
        status=Order.Status.PENDING_PAYMENT,
    )
    out = StringIO()

    call_command("reconcile_orders", "--apply", stdout=out)

    order.refresh_from_db()
    assert order.escrow_fee == Decimal("0.00")
    assert order.total_amount == Decimal("1000.00")


@pytest.mark.django_db
def test_command_does_not_rewrite_paid_totals():
    order = OrderFactory(
        escrow_fee=Decimal("50.00"),
        subtotal=Decimal("1000.00"),
        total_amount=Decimal("1050.00"),
        status=Order.Status.PAID,
    )
    call_command("reconcile_orders", "--apply", stdout=StringIO())

    order.refresh_from_db()
    assert order.total_amount == Decimal("1050.00")
    assert order.escrow_fee == Decimal("50.00")
