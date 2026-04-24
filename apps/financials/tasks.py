from celery import shared_task
import logging

from apps.notifications.utils import notify_payout_failed, notify_payout_processed

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def process_payout_task(self, payout_id):
    """Initiate Paystack transfer for a payout request."""
    from .models import Payout
    try:
        payout = Payout.objects.select_related(
            'bank_account', 'vendor'
        ).get(pk=payout_id)
    except Payout.DoesNotExist:
        return

    try:
        import requests
        from django.conf import settings

        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        }

        # Step 1: Create transfer recipient
        recipient_response = requests.post(
            "https://api.paystack.co/transferrecipient",
            json={
                "type": "nuban",
                "name": payout.bank_account.account_name,
                "account_number": payout.bank_account.account_number,
                "bank_code": payout.bank_account.bank_code,
                "currency": payout.currency,
            },
            headers=headers,
            timeout=30
        )
        recipient_data = recipient_response.json()

        if not recipient_data.get('status'):
            raise Exception(f"Recipient creation failed: {recipient_data}")

        recipient_code = recipient_data['data']['recipient_code']

        # Step 2: Initiate transfer
        transfer_response = requests.post(
            "https://api.paystack.co/transfer",
            json={
                "source": "balance",
                "amount": int(payout.amount * 100),  # kobo
                "recipient": recipient_code,
                "reason": f"Payout {payout.reference}",
                "reference": payout.reference,
            },
            headers=headers,
            timeout=30
        )
        transfer_data = transfer_response.json()

        if transfer_data.get('status'):
            payout.status = Payout.Status.PROCESSING
            notify_payout_processed(payout)
            payout.save(update_fields=['status'])
        else:
            raise Exception(f"Transfer failed: {transfer_data}")

    except Exception as exc:
        logger.exception("process_payout_task failed for payout %s: %s",
                         payout_id, exc)
        payout.status = Payout.Status.FAILED
        notify_payout_failed(payout)
        payout.failure_reason = str(exc)
        payout.save(update_fields=['status', 'failure_reason'])
        raise self.retry(exc=exc, countdown=60)


@shared_task
def release_pending_earnings_task():
    """Move pending earnings to available after escrow period."""
    from .models import VendorEarning, VendorWallet, WalletTransaction
    from django.utils import timezone
    from django.db import transaction

    now = timezone.now()
    pending = VendorEarning.objects.filter(
        status=VendorEarning.Status.PENDING,
        available_at__lte=now,
        is_disputed=False
    )

    count = 0
    for earning in pending:
        with transaction.atomic():
            earning.status = VendorEarning.Status.AVAILABLE
            earning.save(update_fields=['status'])

            wallet, _ = VendorWallet.objects.get_or_create(
                user=earning.vendor,
                store=earning.store,
                defaults={'currency': earning.currency}
            )

            # Move from pending to available
            wallet.pending_balance -= earning.net_amount
            wallet.available_balance += earning.net_amount
            wallet.save(update_fields=['pending_balance', 'available_balance'])

            # Log transaction
            WalletTransaction.objects.create(
                wallet=wallet,
                transaction_type=WalletTransaction.Type.EARNING,
                amount=earning.net_amount,
                description=f"Released earning for order {earning.order.order_number}",
                reference_id=str(earning.id)
            )
            count += 1

    if count > 0:
        logger.info("Released %d pending earnings to available status", count)
    return count
