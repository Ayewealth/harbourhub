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


def wallet_for_store(store, user=None, currency="NGN", *, lock=False):
    """Return (creating if needed) the single wallet for ``store``.

    Writes are always keyed by store; ``user`` is derived from the store when
    it is not supplied.
    """
    from .models import VendorWallet

    if store is None:
        return None
    if user is None:
        user = store.user
    manager = VendorWallet.objects
    if lock:
        manager = manager.select_for_update()
    wallet, _ = manager.get_or_create(
        store=store,
        defaults={"user": user, "currency": currency or "NGN"},
    )
    return wallet


def wallet_for_earning(earning, *, lock=False):
    """Resolve the wallet for an earning, tolerating legacy store-less rows."""
    store = earning.store or getattr(earning.vendor, "store", None)
    if store is None:
        logger.warning(
            "Earning %s has no store; wallet movement skipped", earning.pk)
        return None
    return wallet_for_store(
        store, user=earning.vendor, currency=earning.currency, lock=lock
    )


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

    # Commission is charged on goods only; delivery passes through in full.
    subtotal = money(order.subtotal or Decimal("0.00"))
    delivery = money(order.delivery_fee or Decimal("0.00"))
    gross = money(subtotal + delivery)
    rate = order.commission_rate or order.store.commission_rate
    commission = money(order.commission_amount or Decimal("0.00"))
    if commission <= ZERO:
        commission = money(subtotal * (rate or Decimal("0.00")) / Decimal("100"))
    net = money(gross - commission)
    first_release_at = timezone.now() + timedelta(days=7)

    earning, created = VendorEarning.objects.get_or_create(
        order=order,
        defaults={
            "vendor": order.seller,
            "store": order.store,
            "listing": first_item.listing if first_item else None,
            "earning_type": type_map.get(purchase_type, VendorEarning.EarningType.BUY),
            "gross_amount": gross,
            "commission_rate": rate,
            "commission_amount": commission,
            "net_amount": net,
            "currency": order.currency,
            "status": VendorEarning.Status.PENDING,
            "release_policy": VendorEarning.ReleasePolicy.SPLIT_50_50,
            "first_release_at": first_release_at,
            "final_release_at": None,
            "available_at": first_release_at,
        },
    )

    # Keep the order row authoritative for platform revenue reporting.
    if created and commission > ZERO and not order.commission_amount:
        order.commission_rate = rate
        order.commission_amount = commission
        order.save(update_fields=["commission_rate", "commission_amount"])

    if created:
        wallet = wallet_for_store(
            order.store, user=order.seller, currency=order.currency)
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

    wallet = wallet_for_earning(earning)
    if wallet is None:
        return earning
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

    wallet = wallet_for_earning(earning)
    if wallet is None:
        return earning

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


@transaction.atomic
def allocate_payout(payout):
    """FIFO-allocate released earnings to a payout. Returns the allocated total."""
    from django.db.models import Sum

    from .models import Payout, PayoutAllocation, VendorEarning

    payout = Payout.objects.select_for_update().get(pk=payout.pk)
    remaining = money(payout.amount)
    allocated = ZERO

    open_statuses = (
        Payout.Status.REQUESTED,
        Payout.Status.PROCESSING,
        Payout.Status.FROZEN,
    )

    earnings = (
        VendorEarning.objects.select_for_update()
        .filter(
            vendor=payout.vendor,
            store=payout.store,
            status__in=(
                VendorEarning.Status.AVAILABLE,
                VendorEarning.Status.PARTIALLY_RELEASED,
            ),
        )
        .order_by('available_at', 'created_at')
    )

    for earning in earnings:
        if remaining <= ZERO:
            break
        open_allocated = (
            earning.payout_allocations.filter(
                payout__status__in=open_statuses
            ).aggregate(total=Sum('amount'))['total']
            or ZERO
        )
        available = money(
            earning.released_amount - earning.paid_out_amount - open_allocated)
        if available <= ZERO:
            continue
        take = min(available, remaining)
        PayoutAllocation.objects.create(
            payout=payout, earning=earning, amount=take)
        remaining -= take
        allocated += take

    if remaining > ZERO:
        raise ValueError(
            f'Payout {payout.pk} is under-allocated by {remaining}; '
            'wallet balance is inconsistent.'
        )

    return allocated


@transaction.atomic
def settle_payout(payout):
    """Mark a payout paid and settle only its allocations."""
    from .models import Payout, VendorEarning, VendorWallet

    payout = Payout.objects.select_for_update().get(pk=payout.pk)
    if payout.status == Payout.Status.PAID:
        return payout

    for allocation in payout.allocations.select_related('earning'):
        earning = VendorEarning.objects.select_for_update().get(
            pk=allocation.earning_id)
        earning.paid_out_amount = money(
            earning.paid_out_amount + allocation.amount)
        if earning.paid_out_amount >= earning.net_amount:
            earning.status = VendorEarning.Status.PAID_OUT
        elif earning.status == VendorEarning.Status.AVAILABLE:
            earning.status = VendorEarning.Status.PARTIALLY_RELEASED
        earning.save(update_fields=['paid_out_amount', 'status'])

    wallet = wallet_for_store(
        payout.store, user=payout.vendor, currency=payout.currency, lock=True)
    wallet.total_withdrawn = money(wallet.total_withdrawn + payout.amount)
    wallet.save(update_fields=['total_withdrawn'])

    payout.status = Payout.Status.PAID
    payout.processed_at = timezone.now()
    payout.save(update_fields=['status', 'processed_at'])
    return payout


@transaction.atomic
def fail_payout(payout, reason: str):
    """Reverse allocations and re-credit the reserved amount."""
    from .models import Payout, VendorEarning, VendorWallet, WalletTransaction

    payout = Payout.objects.select_for_update().get(pk=payout.pk)
    if payout.status in (Payout.Status.FAILED, Payout.Status.PAID):
        return payout

    wallet = wallet_for_store(
        payout.store, user=payout.vendor, currency=payout.currency, lock=True)
    VendorWallet.objects.filter(pk=wallet.pk).update(
        available_balance=F('available_balance') + payout.amount
    )

    for allocation in payout.allocations.select_related('earning'):
        earning = VendorEarning.objects.select_for_update().get(
            pk=allocation.earning_id)
        if earning.status == VendorEarning.Status.PROCESSING:
            earning.status = (
                VendorEarning.Status.AVAILABLE
                if earning.released_amount >= earning.net_amount
                else VendorEarning.Status.PARTIALLY_RELEASED
            )
            earning.save(update_fields=['status'])

    payout.allocations.all().delete()
    payout.status = Payout.Status.FAILED
    payout.failure_reason = reason
    payout.save(update_fields=['status', 'failure_reason'])

    WalletTransaction.objects.create(
        wallet=wallet,
        transaction_type=WalletTransaction.Type.REFUND,
        amount=payout.amount,
        description=f'Re-credited failed payout {payout.reference}',
        reference_id=str(payout.pk),
    )
    return payout
