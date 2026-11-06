"""Presentation-independent invoice rows."""
from decimal import Decimal


def invoice_summary_rows(order):
    """Return ``(label, value)`` pairs for the invoice summary.

    The first three rows are the buyer-facing table. The fourth row is the
    seller-side commission note rendered below the total.
    """
    currency = order.currency or "NGN"
    subtotal = order.subtotal or Decimal("0.00")
    delivery = order.delivery_fee or Decimal("0.00")
    total = order.total_amount or Decimal("0.00")
    rate = order.commission_rate or Decimal("0.00")
    commission = order.commission_amount or Decimal("0.00")

    return [
        ("Subtotal", f"{currency} {subtotal:,.2f}"),
        ("Delivery Fee", f"{currency} {delivery:,.2f}"),
        ("Total Amount", f"{currency} {total:,.2f}"),
        (
            f"Sales Commission ({rate}%): {currency} {commission:,.2f} "
            "(deducted from seller proceeds)",
            "",
        ),
    ]
