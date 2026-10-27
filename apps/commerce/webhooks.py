import hashlib
import hmac
import json
import logging

from django.conf import settings
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
            'refund.processed': self._handle_refund_processed,
            'refund.failed': self._handle_refund_failed,
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

    def _handle_transfer_success(self, data: dict) -> bool:
        """Vendor payout was successful."""
        from apps.financials.models import Payout
        from apps.financials.services import settle_payout

        reference = data.get('reference')
        payout = Payout.objects.filter(reference=reference).first()
        if payout is None:
            logger.warning(
                "Webhook: Payout not found for reference %s", reference)
            return False
        settle_payout(payout)
        logger.info(
            "Transfer success processed for reference %s", reference)
        return True

    def _handle_transfer_failed(self, data: dict) -> bool:
        """Vendor payout failed."""
        from apps.financials.models import Payout
        from apps.financials.services import fail_payout

        reference = data.get('reference')
        payout = Payout.objects.filter(reference=reference).first()
        if payout is None:
            return False
        fail_payout(payout, data.get('reason') or 'Transfer failed')
        logger.info(
            "Transfer failed processed for reference %s", reference)
        return True

    def _handle_transfer_reversed(self, data: dict) -> bool:
        """Transfer was reversed, re-credit vendor balance."""
        return self._handle_transfer_failed(data)

    def _handle_refund_processed(self, data: dict) -> bool:
        from apps.commerce.models import Refund
        from apps.commerce.services.refunds import finalize_refund

        reference = data.get('reference') or data.get('transaction_reference')
        refund = Refund.objects.filter(reference=reference).first()
        if refund is None:
            refund = Refund.objects.filter(
                payment__reference=reference).first()
        if refund is None:
            return False
        finalize_refund(refund, data)
        return True

    def _handle_refund_failed(self, data: dict) -> bool:
        from apps.commerce.models import Refund

        reference = data.get('reference') or data.get('transaction_reference')
        refund = Refund.objects.filter(reference=reference).first()
        if refund is None:
            return False
        refund.status = Refund.Status.FAILED
        refund.gateway_response = data
        refund.save(update_fields=['status', 'gateway_response'])
        return True
