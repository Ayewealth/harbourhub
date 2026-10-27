import logging
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import F
from django.utils import timezone

logger = logging.getLogger(__name__)

ZERO = Decimal("0.00")


def money(value) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@transaction.atomic
def accrue_earning(order):
    """Create exactly one earning for a paid order and credit pending balance."""
    from apps.commerce.models import OrderItem  # noqa: F401  (keeps app import local)
    from .models import VendorEarning, VendorWallet, WalletTransaction

    if order is None:
        return None
    if not order.store_id or not order.seller_id:
        logger.warning(
            "Skipping earning accrual for order %s: no store or seller", order.pk)
        return None

    items = order.items.all()
    first_item = items.first()
    type_map = {
        "buy": VendorEarning.EarningType.BUY,
        "hire": VendorEarning.EarningType.RENT,
        "rent": VendorEarning.EarningType.RENT,
        "lease": VendorEarning.EarningType.LEASE,
    }
    purchase_type = first_item.purchase_type if first_item else "buy"

    earning, created = VendorEarning.objects.get_or_create(
        order=order,
        defaults={
            "vendor": order.seller,
            "store": order.store,
            "listing": first_item.listing if first_item else None,
            "earning_type": type_map.get(purchase_type, VendorEarning.EarningType.BUY),
            "gross_amount": order.subtotal or order.total_amount,
            "commission_rate": order.store.commission_rate,
            "currency": order.currency,
            "status": VendorEarning.Status.PENDING,
            "available_at": timezone.now() + timedelta(days=7),
        },
    )

    if created:
        wallet, _ = VendorWallet.objects.get_or_create(
            user=order.seller,
            store=order.store,
            defaults={"currency": order.currency},
        )
        VendorWallet.objects.filter(pk=wallet.pk).update(
            pending_balance=F("pending_balance") + earning.net_amount
        )
        WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type=WalletTransaction.Type.EARNING,
            amount=earning.net_amount,
            description=f"Pending earning for order {order.order_number}",
            reference_id=str(earning.id),
        )

    return earning


@transaction.atomic
def release_earning(earning, amount):
    """Move `amount` from pending to available. Idempotent guard on released_amount."""
    from .models import VendorEarning, VendorWallet, WalletTransaction

    earning = VendorEarning.objects.select_for_update().get(pk=earning.pk)
    amount = money(amount)

    if earning.status in (VendorEarning.Status.REVERSED, VendorEarning.Status.PAID_OUT):
        return earning
    if amount <= ZERO:
        return earning
    if earning.released_amount + amount > earning.net_amount:
        amount = earning.net_amount - earning.released_amount
        if amount <= ZERO:
            return earning

    wallet, _ = VendorWallet.objects.get_or_create(
        user=earning.vendor,
        store=earning.store,
        defaults={"currency": earning.currency},
    )
    VendorWallet.objects.filter(pk=wallet.pk).update(
        pending_balance=F("pending_balance") - amount,
        available_balance=F("available_balance") + amount,
    )

    earning.released_amount += amount
    if earning.released_amount >= earning.net_amount:
        earning.status = VendorEarning.Status.AVAILABLE
    else:
        earning.status = VendorEarning.Status.PARTIALLY_RELEASED
    earning.save(update_fields=["released_amount", "status"])

    WalletTransaction.objects.create(
        wallet=wallet,
        transaction_type=WalletTransaction.Type.EARNING,
        amount=amount,
        description=(
            f"Released earning for order "
            f"{earning.order.order_number if earning.order else earning.pk}"
        ),
        reference_id=str(earning.id),
    )
    return earning


@transaction.atomic
def reverse_earning(earning, reason: str):
    """Reverse an earning after a refund. Balances may go negative on purpose."""
    from .models import VendorEarning, VendorWallet, WalletTransaction

    earning = VendorEarning.objects.select_for_update().get(pk=earning.pk)
    if earning.status == VendorEarning.Status.REVERSED:
        return earning

    wallet, _ = VendorWallet.objects.get_or_create(
        user=earning.vendor,
        store=earning.store,
        defaults={"currency": earning.currency},
    )

    unreleased = money(earning.net_amount - earning.released_amount)
    if unreleased > ZERO:
        VendorWallet.objects.filter(pk=wallet.pk).update(
            pending_balance=F("pending_balance") - unreleased
        )
    if earning.released_amount > ZERO:
        VendorWallet.objects.filter(pk=wallet.pk).update(
            available_balance=F("available_balance") - earning.released_amount
        )

    earning.status = VendorEarning.Status.REVERSED
    earning.save(update_fields=["status"])

    WalletTransaction.objects.create(
        wallet=wallet,
        transaction_type=WalletTransaction.Type.REFUND,
        amount=-earning.net_amount,
        description=reason,
        reference_id=str(earning.id),
    )
    return earning
