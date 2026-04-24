import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from apps.notifications.utils import notify_order_paid

from .models import Order, OrderActivity, Payment

logger = logging.getLogger(__name__)


def verify_paystack_signature(body: bytes, signature: str) -> bool:
    """Verify that the webhook came from Paystack."""
    secret = settings.PAYSTACK_SECRET_KEY.encode('utf-8')
    expected = hmac.new(secret, body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)


@method_decorator(csrf_exempt, name='dispatch')
class PaystackWebhookView(APIView):
    """
    Handle Paystack webhook events.
    Docs: https://paystack.com/docs/payments/webhooks
    """
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        signature = request.headers.get('x-paystack-signature', '')
        body = request.body

        if not verify_paystack_signature(body, signature):
            logger.warning("Invalid Paystack webhook signature")
            return Response(
                {'error': 'Invalid signature'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return Response(
                {'error': 'Invalid JSON'},
                status=status.HTTP_400_BAD_REQUEST
            )

        event = data.get('event')
        event_data = data.get('data', {})

        logger.info("Paystack webhook received: %s", event)

        handlers = {
            'charge.success': self._handle_charge_success,
            'transfer.success': self._handle_transfer_success,
            'transfer.failed': self._handle_transfer_failed,
            'transfer.reversed': self._handle_transfer_reversed,
        }

        handler = handlers.get(event)
        if handler:
            try:
                handler(event_data)
            except Exception as exc:
                logger.exception(
                    "Webhook handler error for %s: %s", event, exc)
                # Still return 200 to prevent Paystack retries
                # for non-retryable errors

        return Response({'status': 'ok'})

    @transaction.atomic
    def _handle_charge_success(self, data: dict):
        """Payment was successful."""
        reference = data.get('reference')
        if not reference:
            return

        try:
            payment = Payment.objects.select_related(
                'order'
            ).get(reference=reference)
        except Payment.DoesNotExist:
            logger.warning(
                "Webhook: Payment not found for reference %s", reference)
            return

        if payment.status == Payment.Status.SUCCESS:
            return  # Already processed, idempotent

        payment.status = Payment.Status.SUCCESS
        payment.paid_at = timezone.now()
        payment.gateway_response = data
        payment.save(update_fields=[
            'status', 'paid_at', 'gateway_response'])

        order = payment.order
        order.status = Order.Status.PAID
        order.save(update_fields=['status'])

        notify_order_paid(order)

        OrderActivity.objects.create(
            order=order,
            event_type=OrderActivity.EventType.PAYMENT_CONFIRMED,
            message="Payment confirmed via Paystack. Funds held in escrow."
        )

        # Create vendor earning
        self._create_vendor_earning(order)

        logger.info("Charge success processed for reference %s", reference)

    def _create_vendor_earning(self, order: Order):
        from apps.financials.models import VendorEarning
        import datetime

        if VendorEarning.objects.filter(order=order).exists():
            return

        earning = VendorEarning.objects.create(
            vendor=order.seller,
            store=order.store,
            order=order,
            listing=order.listing,
            earning_type=order.order_type,
            gross_amount=order.subtotal,
            commission_rate=getattr(
                order.store, 'commission_rate', 5.00) if order.store else 5.00,
            currency=order.currency,
            status=VendorEarning.Status.PENDING,
            available_at=timezone.now() + datetime.timedelta(days=7)
        )

        # Update wallet pending balance
        from apps.financials.models import VendorWallet
        wallet, _ = VendorWallet.objects.get_or_create(
            user=order.seller,
            store=order.store,
            defaults={'currency': order.currency}
        )
        wallet.pending_balance += earning.net_amount
        wallet.save(update_fields=['pending_balance'])

    @transaction.atomic
    def _handle_transfer_success(self, data: dict):
        """Vendor payout was successful."""
        from apps.financials.models import Payout, VendorEarning, VendorWallet, WalletTransaction

        reference = data.get('reference')
        if not reference:
            return

        try:
            payout = Payout.objects.get(reference=reference)
        except Payout.DoesNotExist:
            logger.warning(
                "Webhook: Payout not found for reference %s", reference)
            return

        payout.status = Payout.Status.PAID
        payout.processed_at = timezone.now()
        payout.save(update_fields=['status', 'processed_at'])

        # Mark vendor earnings as paid out
        VendorEarning.objects.filter(
            payout=payout
        ).update(status=VendorEarning.Status.PAID_OUT)

        # Update wallet total withdrawn
        wallet, _ = VendorWallet.objects.get_or_create(user=payout.vendor)
        wallet.total_withdrawn += payout.amount
        wallet.save(update_fields=['total_withdrawn'])

        logger.info(
            "Transfer success processed for reference %s", reference)

    @transaction.atomic
    def _handle_transfer_failed(self, data: dict):
        """Vendor payout failed."""
        from apps.financials.models import Payout, VendorEarning, VendorWallet, WalletTransaction

        reference = data.get('reference')
        if not reference:
            return

        try:
            payout = Payout.objects.get(reference=reference)
        except Payout.DoesNotExist:
            return

        payout.status = Payout.Status.FAILED
        payout.failure_reason = data.get(
            'gateway_response', 'Transfer failed')
        payout.save(update_fields=['status', 'failure_reason'])

        # Re-credit wallet
        wallet, _ = VendorWallet.objects.get_or_create(user=payout.vendor)
        wallet.available_balance += payout.amount
        wallet.save(update_fields=['available_balance'])

        # Log transaction
        WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type=WalletTransaction.Type.REFUND,
            amount=payout.amount,
            description=f"Refunded payout {payout.reference} (Transfer failed)",
            reference_id=str(payout.id)
        )

        # Also release earnings back (historical tracking)
        VendorEarning.objects.filter(
            payout=payout
        ).update(
            status=VendorEarning.Status.AVAILABLE,
            payout=None
        )

        logger.info(
            "Transfer failed processed for reference %s", reference)

    @transaction.atomic
    def _handle_transfer_reversed(self, data: dict):
        """Transfer was reversed, re-credit vendor balance."""
        from apps.financials.models import Payout, VendorEarning, VendorWallet, WalletTransaction

        reference = data.get('reference')
        if not reference:
            return

        try:
            payout = Payout.objects.get(reference=reference)
        except Payout.DoesNotExist:
            return

        payout.status = Payout.Status.FAILED
        payout.failure_reason = "Transfer reversed by Paystack"
        payout.save(update_fields=['status', 'failure_reason'])

        # Re-credit wallet
        wallet, _ = VendorWallet.objects.get_or_create(user=payout.vendor)
        wallet.available_balance += payout.amount
        wallet.save(update_fields=['available_balance'])

        # Log transaction
        WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type=WalletTransaction.Type.REFUND,
            amount=payout.amount,
            description=f"Refunded payout {payout.reference} (Transfer reversed)",
            reference_id=str(payout.id)
        )

        # Re-credit earnings back
        VendorEarning.objects.filter(
            payout=payout
        ).update(
            status=VendorEarning.Status.AVAILABLE,
            payout=None
        )

        logger.info(
            "Transfer reversed for reference %s", reference)
