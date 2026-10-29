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

    if payout.status == Payout.Status.FROZEN:
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
    """
    Release the first tranche on day 7 and the remainder on completion.

    Rows are locked with skip_locked so concurrent workers cannot
    double-release the same tranche.
    """
    from django.db import transaction
    from django.db.models import Q
    from django.utils import timezone

    from .models import VendorEarning
    from .services import money, release_earning

    now = timezone.now()
    released = 0

    with transaction.atomic():
        candidates = (
            VendorEarning.objects.select_for_update(skip_locked=True)
            .filter(is_disputed=False)
            .filter(
                Q(
                    status=VendorEarning.Status.PENDING,
                    first_release_at__lte=now,
                )
                | Q(
                    status=VendorEarning.Status.PARTIALLY_RELEASED,
                    final_release_at__lte=now,
                )
            )
            .order_by('first_release_at')
        )

        for earning in candidates.iterator():
            if earning.order_id is None:
                logger.warning(
                    "Skipping orphan earning %s (no order)", earning.pk)
                continue

            if earning.status == VendorEarning.Status.PENDING:
                if earning.release_policy == VendorEarning.ReleasePolicy.FULL:
                    amount = money(
                        earning.net_amount - earning.released_amount)
                else:
                    target = money(earning.net_amount / 2)
                    amount = money(target - earning.released_amount)
            else:
                amount = money(earning.net_amount - earning.released_amount)

            if amount <= 0:
                continue
            release_earning(earning, amount)
            released += 1

    if released:
        logger.info("Released %d earning tranches", released)
    return released
