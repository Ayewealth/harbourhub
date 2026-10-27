import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework.response import Response
from rest_framework import status, serializers
from rest_framework.views import APIView
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from .models import Payment, WebhookEvent
from .services.payments import finalize_payment

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

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(name='PaystackWebhookResponse', fields={'status': serializers.CharField()}),
            400: inline_serializer(name='PaystackWebhookError', fields={'error': serializers.CharField()})
        }
    )
    def post(self, request):
        signature = request.headers.get('x-paystack-signature', '')
        body = request.body

        if not verify_paystack_signature(body, signature):
            logger.warning("Invalid Paystack webhook signature")
            return Response(
                {'error': 'Invalid signature'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return Response(
                {'error': 'Invalid JSON'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        event = payload.get('event', '')
        data = payload.get('data', {}) or {}

        event_id = str(
            data.get('id') or data.get('reference')
            or hashlib.sha256(body).hexdigest()
        )
        event_row, created = WebhookEvent.objects.get_or_create(
            provider='paystack',
            event_type=event,
            gateway_event_id=event_id,
            defaults={'payload': payload},
        )
        if not created:
            return Response({'status': 'ok', 'detail': 'duplicate'})

        logger.info("Paystack webhook received: %s", event)

        handler = {
            'charge.success': self._handle_charge_success,
            'charge.failed': self._handle_charge_failed,
            'transfer.success': self._handle_transfer_success,
            'transfer.failed': self._handle_transfer_failed,
            'transfer.reversed': self._handle_transfer_reversed,
        }.get(event)

        if handler is None:
            event_row.status = WebhookEvent.Status.IGNORED
            event_row.save(update_fields=['status'])
            return Response({'status': 'ok'})

        try:
            handled = handler(data)
        except Exception as exc:
            logger.exception("Webhook handler failed for %s: %s", event, exc)
            event_row.status = WebhookEvent.Status.FAILED
            event_row.error = str(exc)
            event_row.save(update_fields=['status', 'error'])
            return Response(
                {'error': 'handler failed'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        event_row.status = (
            WebhookEvent.Status.PROCESSED if handled
            else WebhookEvent.Status.IGNORED
        )
        event_row.save(update_fields=['status'])
        return Response({'status': 'ok'})

    def _handle_charge_success(self, data: dict) -> bool:
        reference = data.get('reference')
        if not reference:
            return False
        try:
            payment = Payment.objects.get(reference=reference)
        except Payment.DoesNotExist:
            logger.warning(
                "Webhook: Payment not found for reference %s", reference)
            return False
        return finalize_payment(payment, data)

    def _handle_charge_failed(self, data: dict) -> bool:
        reference = data.get('reference')
        if not reference:
            return False
        updated = Payment.objects.filter(
            reference=reference, status=Payment.Status.PENDING,
        ).update(status=Payment.Status.FAILED)
        return bool(updated)

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
