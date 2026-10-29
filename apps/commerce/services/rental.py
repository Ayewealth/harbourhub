from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.financials.models import VendorEarning, VendorWallet
from apps.financials.services import money, wallet_for_store
from apps.notifications.utils import notify_rental_extended

from ..models import OrderActivity, RentalExtension

ZERO = Decimal("0.00")


@transaction.atomic
def apply_rental_extension(extension):
    """Apply a paid extension exactly once."""
    extension = RentalExtension.objects.select_for_update().get(pk=extension.pk)
    if extension.status != RentalExtension.Status.PENDING_PAYMENT:
        return extension

    item = extension.order_item
    order = item.order

    item.rental_end_date = extension.new_end_date
    item.duration_days = (item.duration_days or 0) + extension.additional_days
    item.save(update_fields=["rental_end_date", "duration_days"])

    extra = money(extension.amount)
    order.subtotal = money((order.subtotal or ZERO) + extra)
    order.total_amount = money((order.total_amount or ZERO) + extra)

    earning = VendorEarning.objects.select_for_update().filter(
        order=order
    ).first()

    if earning is not None:
        extra_commission = money(
            extra * (earning.commission_rate or ZERO) / Decimal("100")
        )
        extra_net = money(extra - extra_commission)

        earning.gross_amount = money(earning.gross_amount + extra)
        earning.commission_amount = money(
            earning.commission_amount + extra_commission
        )
        earning.net_amount = money(earning.net_amount + extra_net)
        update_fields = [
            "gross_amount",
            "commission_amount",
            "net_amount",
        ]

        # The extra amount joins the normal hold schedule. If the first
        # tranche was already released, hold the extra until a fresh
        # seven-day window has elapsed.
        if earning.released_amount > ZERO:
            earning.final_release_at = timezone.now() + timedelta(days=7)
            update_fields.append("final_release_at")

        if earning.status not in (
            VendorEarning.Status.REVERSED,
            VendorEarning.Status.PROCESSING,
        ):
            if earning.released_amount <= ZERO:
                new_status = VendorEarning.Status.PENDING
            elif earning.released_amount < earning.net_amount:
                new_status = VendorEarning.Status.PARTIALLY_RELEASED
            else:
                new_status = earning.status
            if new_status != earning.status:
                earning.status = new_status
                update_fields.append("status")

        earning.save(update_fields=update_fields)

        wallet = wallet_for_store(
            order.store, user=order.store.user, currency=order.currency
        )
        VendorWallet.objects.filter(pk=wallet.pk).update(
            pending_balance=F("pending_balance") + extra_net
        )
    else:
        extra_commission = money(
            extra
            * (order.commission_rate or ZERO)
            / Decimal("100")
        )

    order.commission_amount = money(
        (order.commission_amount or ZERO) + extra_commission
    )
    order.save(
        update_fields=["subtotal", "total_amount", "commission_amount"]
    )

    extension.status = RentalExtension.Status.PAID
    extension.applied_at = timezone.now()
    extension.save(update_fields=["status", "applied_at"])

    OrderActivity.objects.create(
        order=order,
        event_type=OrderActivity.EventType.RENTAL_EXTENDED,
        message=f"Rental extended to {extension.new_end_date}.",
    )
    transaction.on_commit(lambda: notify_rental_extended(order, item))
    return extension
