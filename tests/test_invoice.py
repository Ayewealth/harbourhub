from decimal import Decimal

import pytest

from apps.commerce.services.invoice import invoice_summary_rows


@pytest.mark.django_db
def test_invoice_summary_uses_commission_not_escrow():
    from .factories import OrderFactory

    order = OrderFactory(
        subtotal=Decimal("1000.00"),
        delivery_fee=Decimal("150.00"),
        total_amount=Decimal("1150.00"),
        commission_rate=Decimal("5.00"),
        commission_amount=Decimal("50.00"),
        escrow_fee=Decimal("0.00"),
    )

    rows = invoice_summary_rows(order)

    labels = [label for label, _ in rows]
    assert labels[0] == "Subtotal"
    assert labels[1] == "Delivery Fee"
    assert labels[2] == "Total Amount"
    assert not any("Escrow" in label for label in labels)
    values = dict(rows)
    assert values["Subtotal"] == "NGN 1,000.00"
    assert values["Delivery Fee"] == "NGN 150.00"
    assert values["Total Amount"] == "NGN 1,150.00"
    assert "Sales Commission (5.00%)" in labels[3]
    assert "NGN 50.00" in labels[3]
    assert "deducted from seller proceeds" in labels[3]


@pytest.mark.django_db
def test_invoice_pdf_renders(auth_client):
    from .factories import OrderFactory

    order = OrderFactory(
        subtotal=Decimal("1000.00"),
        delivery_fee=Decimal("150.00"),
        total_amount=Decimal("1150.00"),
        commission_rate=Decimal("5.00"),
        commission_amount=Decimal("50.00"),
    )

    response = auth_client(order.buyer).get(
        f"/commerce/orders/{order.pk}/invoice/pdf/"
    )

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
