import uuid
import hmac
import hashlib
import logging
import requests

from datetime import timedelta
from decimal import Decimal
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.utils.dateparse import parse_date
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample, inline_serializer, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from rest_framework import generics, permissions, status, exceptions, serializers
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import get_object_or_404
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from apps.commerce.models import Order, OrderActivity
from apps.commerce.paystack import initialize_transaction, verify_transaction
from apps.admin_panel.auth import has_admin_module_permission, HasAdminModulePermission
from apps.admin_panel.constants import AdminModule
from apps.core.currency import CurrencyRateUnavailable, convert_currency, convert_to_ngn
from apps.financials.services import money
from apps.notifications.utils import notify_order_cancelled, notify_order_placed, notify_order_shipped, notify_quote_received, notify_quote_responded
from apps.analytics.posthog_utils import (
    track_quote_requested, track_order_placed,
    track_item_added_to_cart
)


from .filters import OrderFilter, QuoteRequestFilter
from .models import (
    Cart,
    CartItem,
    Order,
    OrderActivity,
    OrderItem,
    Payment,
    QuoteRequest,
    Dispute,
    RentalExtension,
)
from .serializers import (
    CartItemCreateSerializer,
    CartItemSerializer,
    CartSerializer,
    CheckoutSerializer,
    OrderCreateSerializer,
    OrderSerializer,
    QuoteRequestCreateSerializer,
    QuoteRequestSerializer,
    OrderActivitySerializer,
    QuoteRequestVendorUpdateSerializer,
    DisputeSerializer,
    DisputeResolutionSerializer,
    OrderTrackingDetailSerializer,
    OrderListTrackingSummarySerializer,
)
from .services.orders import InvalidTransition, transition


# Cart purchase types use ``rent``; orders expose ``hire`` for the same thing.
PURCHASE_TYPE_MAP = {
    CartItem.PurchaseType.BUY: Order.OrderType.BUY,
    CartItem.PurchaseType.RENT: Order.OrderType.HIRE,
    CartItem.PurchaseType.LEASE: Order.OrderType.LEASE,
}

logger = logging.getLogger(__name__)


@extend_schema_view(
    get=extend_schema(summary="List quote requests"),
    post=extend_schema(
        summary="Create quote request",
        examples=[
            OpenApiExample(
                "Buy quote request",
                value={
                    "listing": 104,
                    "store": 1,
                    "purchase_type": "buy",
                    "quantity": 2,
                    "preferred_delivery_date": "2026-04-30",
                    "delivery_location": "Port Harcourt, Rivers, Nigeria",
                    "notes": "Need urgent delivery and installation included."
                },
                request_only=True,
            ),
            OpenApiExample(
                "Rent quote request",
                value={
                    "listing": 104,
                    "store": 1,
                    "purchase_type": "rent",
                    "quantity": 1,
                    "duration_days": 65,
                    "preferred_delivery_date": "2026-05-05",
                    "delivery_location": "Abuja, FCT, Nigeria",
                    "notes": "Need it for a temporary project site."
                },
                request_only=True,
            ),
        ],
    ),
)
@extend_schema_view(
    post=extend_schema(operation_id="commerce_quotes_create"),
    get=extend_schema(operation_id="commerce_quotes_list"),
)
class QuoteRequestListCreateView(generics.ListCreateAPIView):
    filter_backends = [DjangoFilterBackend]
    filterset_class = QuoteRequestFilter

    def get_permissions(self):
        return [permissions.IsAuthenticated()]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return QuoteRequestCreateSerializer
        return QuoteRequestSerializer

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return QuoteRequest.objects.none()
        user = self.request.user
        qs = QuoteRequest.objects.select_related(
            "listing", "buyer", "store"
        ).order_by("-created_at")
        if user.is_staff and self.request.query_params.get("all") == "true":
            return qs
        return qs.filter(Q(buyer=user) | Q(listing__user=user))

    def perform_create(self, serializer):
        listing = serializer.validated_data.get('listing')
        quantity = serializer.validated_data.get('quantity', 1)
        duration_days = serializer.validated_data.get('duration_days', 1) or 1
        
        base_price = listing.price or 0
        purchase_type = serializer.validated_data.get('purchase_type')
        if purchase_type in ['rent', 'lease']:
            standard_price = base_price * quantity * duration_days
        else:
            standard_price = base_price * quantity
            
        quote = serializer.save(buyer=self.request.user, standard_price=standard_price)
        notify_quote_received(quote)
        track_quote_requested(self.request.user, quote)


@extend_schema_view(
    get=extend_schema(summary="Retrieve quote request"),
    patch=extend_schema(summary="Update quote request"),
    put=extend_schema(summary="Replace quote request"),
)
class QuoteRequestDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = QuoteRequestSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "pk"

    def get_queryset(self):
        user = self.request.user
        qs = QuoteRequest.objects.select_related("listing", "buyer", "store")
        if user.is_staff:
            return qs
        return qs.filter(Q(buyer=user) | Q(listing__user=user))


class QuoteRequestVendorUpdateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=QuoteRequestVendorUpdateSerializer,
        responses={200: QuoteRequestVendorUpdateSerializer}
    )
    def patch(self, request, pk):
        quote = get_object_or_404(
            QuoteRequest,
            pk=pk,
            listing__user=request.user
        )

        serializer = QuoteRequestVendorUpdateSerializer(
            quote,
            data=request.data,
            partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data)


class QuoteRequestActionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Quote action",
        operation_id="commerce_quote_action_post",
        request=None,
        examples=[
            OpenApiExample("Respond to quote", value={"action": "respond"}, request_only=True),
            OpenApiExample("Cancel quote", value={"action": "cancel"}, request_only=True),
            OpenApiExample("Convert quote", value={"action": "convert"}, request_only=True),
        ],
        responses={
            200: inline_serializer(name='QuoteActionResponse', fields={'message': serializers.CharField()}),
            400: inline_serializer(name='QuoteActionError', fields={'error': serializers.CharField()}),
            403: inline_serializer(name='QuoteActionForbidden', fields={'error': serializers.CharField()})
        }
    )
    def post(self, request, pk, action):
        qs = QuoteRequest.objects.filter(
            Q(buyer=request.user) | Q(listing__user=request.user)
        )
        quote = get_object_or_404(qs, pk=pk)

        if action == 'cancel':
            if request.user != quote.buyer:
                return Response({'error': 'Only buyer can cancel'}, status=403)
            if quote.status != QuoteRequest.Status.PENDING:
                return Response({'error': 'Only pending quotes can be cancelled'}, status=400)
            quote.status = QuoteRequest.Status.CANCELLED

        elif action == 'decline':
            if request.user != quote.buyer:
                return Response({'error': 'Only buyer can decline'}, status=403)
            if quote.status not in [QuoteRequest.Status.PENDING, QuoteRequest.Status.RESPONDED]:
                return Response({'error': 'Cannot decline this quote'}, status=400)
            quote.status = QuoteRequest.Status.CANCELLED

        elif action == 'respond':
            if request.user != quote.listing.user:
                return Response({'error': 'Only listing owner can respond'}, status=403)
            if quote.status != QuoteRequest.Status.PENDING:
                return Response({'error': 'Only pending quotes can be responded to'}, status=400)
            quote.status = QuoteRequest.Status.RESPONDED
            notify_quote_responded(quote)

        elif action == 'convert':
            if quote.status != QuoteRequest.Status.RESPONDED:
                return Response({'error': 'Only responded quotes can be converted'}, status=400)
            quote.status = QuoteRequest.Status.CONVERTED

        else:
            return Response({'error': 'Invalid action'}, status=400)

        quote.save(update_fields=['status'])
        return Response({'message': f'Quote {action}ed successfully'})


class MoveQuoteToCartView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=inline_serializer(
            name='MoveQuoteToCartRequest',
            fields={'quoted_price': serializers.DecimalField(max_digits=14, decimal_places=2, required=False)}
        ),
        responses={
            200: inline_serializer(
                name='MoveQuoteToCartResponse',
                fields={
                    'message': serializers.CharField(),
                    'cart_item': inline_serializer(
                        name='MoveQuoteCartItem',
                        fields={
                            'listing': serializers.CharField(),
                            'quantity': serializers.IntegerField(),
                            'unit_price': serializers.CharField(),
                        }
                    )
                }
            )
        }
    )
    @transaction.atomic
    def post(self, request, pk):
        quote = get_object_or_404(
            QuoteRequest,
            pk=pk,
            buyer=request.user,
            status=QuoteRequest.Status.RESPONDED
        )

        cart, _ = Cart.objects.get_or_create(buyer=request.user)

        # vendor_price is the total agreed contract price for the entire quote
        total_price = request.data.get('quoted_price') or quote.total_quote_price or quote.listing.price

        CartItem.objects.update_or_create(
            cart=cart,
            listing=quote.listing,
            purchase_type=quote.purchase_type,
            defaults={
                'quantity': quote.quantity,
                'unit_price': quote.listing.price,   # ← original listing price, not overwritten
                'store': quote.store,
                'duration_days': quote.duration_days,
                'quote_request': quote,
                'locked_subtotal': total_price,       # ← locked vendor contract price
            }
        )

        # Mark quote as converted
        quote.status = QuoteRequest.Status.CONVERTED
        quote.save(update_fields=['status'])

        return Response({
            'message': 'Quote moved to cart successfully.',
            'cart_item': {
                'listing': quote.listing.title,
                'quantity': quote.quantity,
                'unit_price': str(total_price),
            }
        })


@extend_schema_view(
    get=extend_schema(summary="List orders"),
    post=extend_schema(
        summary="Create order",
        examples=[
            OpenApiExample(
                "Create buy order",
                value={
                    "purchase_type": "buy",
                    "seller": 106,
                    "listing": 104,
                    "store": 1,
                    "currency": "NGN",
                    "total_amount": "4200000.00",
                    "status": "pending_payment",
                    "placed_at": "2026-04-20T10:00:00Z",
                    "quote_request": 12,
                    "extra": {
                        "delivery_address": "Port Harcourt, Rivers",
                        "payment_method": "bank_transfer"
                    }
                },
                request_only=True,
            ),
            OpenApiExample(
                "Create hire order",
                value={
                    "purchase_type": "hire",
                    "seller": 106,
                    "listing": 104,
                    "store": 1,
                    "currency": "NGN",
                    "total_amount": "850000.00",
                    "status": "draft",
                    "placed_at": None,
                    "quote_request": 15,
                    "extra": {
                        "hire_duration_days": 30,
                        "site_location": "Lagos"
                    }
                },
                request_only=True,
            ),
        ],
    ),
)
@extend_schema_view(
    post=extend_schema(operation_id="commerce_orders_create_new"),
    get=extend_schema(operation_id="commerce_orders_list"),
)
class OrderListCreateView(generics.ListCreateAPIView):
    filter_backends = [DjangoFilterBackend]
    filterset_class = OrderFilter
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return OrderCreateSerializer
        return OrderSerializer

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Order.objects.none()
        user = self.request.user
        qs = Order.objects.select_related(
            "buyer", "seller", "store"
        ).order_by("-created_at")
        if user.is_staff and self.request.query_params.get("all") == "true":
            return qs
        return qs.filter(Q(buyer=user) | Q(seller=user))


class OrderDetailView(generics.RetrieveAPIView):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Order.objects.none()
        user = self.request.user
        return Order.objects.filter(
            Q(buyer=user) | Q(seller=user)
        ).select_related("buyer", "seller", "store")

    @extend_schema(operation_id="commerce_orders_cancel_action_post", request=None, responses={200: inline_serializer(name='OrderCancelResponse', fields={'message': serializers.CharField()})})
    def post(self, request, pk=None):
        """Cancel an unpaid order, or request a refund for a paid one."""
        order = self.get_object()
        if request.user not in (order.buyer, order.seller):
            return Response({'error': 'Permission denied'}, status=403)

        if order.status in (Order.Status.DRAFT, Order.Status.PENDING_PAYMENT):
            try:
                transition(
                    order,
                    "order_cancelled",
                    actor=request.user,
                    reason=(request.data.get("reason") or "").strip(),
                    message="Order has been cancelled.",
                )
            except InvalidTransition as exc:
                return Response({'error': str(exc)}, status=400)

            notify_order_cancelled(order, cancelled_by=request.user)
            return Response({'message': 'Order cancelled successfully'})

        if order.status != Order.Status.PAID:
            return Response(
                {'error': 'Order cannot be cancelled at this stage'}, status=400
            )

        if not order.checkout_session_id:
            return Response(
                {'error': 'No successful payment found for this order'}, status=400
            )
        payment = Payment.objects.filter(
            checkout_session=order.checkout_session,
            status=Payment.Status.SUCCESS,
        ).first()
        if payment is None:
            return Response(
                {'error': 'No successful payment found for this order'}, status=400
            )

        from .services.refunds import RefundError, request_refund
        reason = (request.data.get('reason') or 'Order cancelled by customer').strip()
        try:
            refund = request_refund(
                payment, payment.amount, reason, actor=request.user
            )
        except RefundError as exc:
            return Response({'error': str(exc)}, status=400)

        OrderActivity.objects.create(
            order=order,
            event_type=OrderActivity.EventType.ORDER_REFUNDED,
            message=f"Refund requested: {reason}.",
        )
        return Response(
            {
                'message': (
                    'Refund requested. The order will be cancelled once the '
                    'gateway confirms.'
                ),
                'refund_id': refund.id,
                'refund_status': refund.status,
            },
            status=202,
        )


@extend_schema_view(
    post=extend_schema(
        summary="Legacy rental extension (per order)",
        description=(
            "Deprecated. Rentals are extended per item and require payment; "
            "this endpoint returns the correct item endpoint to use."
        ),
        request=None,
        responses={
            400: inline_serializer(
                name='LegacyExtendRentalError',
                fields={
                    'error': serializers.CharField(),
                    'item_id': serializers.IntegerField(),
                    'endpoint': serializers.CharField(),
                },
            ),
        },
    )
)
class OrderExtendRentalView(APIView):
    """Legacy per-order endpoint kept only to redirect clients."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        order = get_object_or_404(Order, pk=pk, buyer=request.user)
        item = order.items.order_by("id").first()
        if item is None:
            return Response({"error": "Order has no item."}, status=400)
        return Response(
            {
                "error": (
                    "Rentals are extended per item and require payment. "
                    "Use the item endpoint."
                ),
                "item_id": item.id,
                "endpoint": (
                    f"/commerce/orders/{order.id}/items/{item.id}"
                    "/extend-rental/"
                ),
            },
            status=400,
        )


class OrderItemExtendRentalView(APIView):
    """Create a payable extension for one hire/lease item.

    The item's dates only move once the extension payment is confirmed.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Extend one rental item (paid)",
        request=inline_serializer(
            name="OrderItemExtendRentalRequest",
            fields={
                "duration_days": serializers.IntegerField(
                    required=False,
                    help_text="Number of extra days",
                ),
                "new_end_date": serializers.DateField(
                    required=False,
                    help_text="Alternative: the new rental end date",
                ),
            },
        ),
        responses={
            201: inline_serializer(
                name='OrderItemExtendRentalResponse',
                fields={
                    'message': serializers.CharField(),
                    'extension_id': serializers.IntegerField(),
                    'amount': serializers.CharField(),
                    'authorization_url': serializers.CharField(),
                    'new_end_date': serializers.CharField(),
                },
            ),
            400: inline_serializer(
                name='OrderItemExtendRentalError',
                fields={'error': serializers.CharField()},
            ),
            502: inline_serializer(
                name='OrderItemExtendRentalGatewayError',
                fields={'error': serializers.CharField()},
            ),
        },
    )
    def post(self, request, pk, item_id):
        order = get_object_or_404(
            Order.objects.filter(buyer=request.user), pk=pk
        )
        item = get_object_or_404(
            OrderItem.objects.filter(
                pk=item_id,
                order=order,
                purchase_type__in=[
                    Order.OrderType.HIRE, Order.OrderType.LEASE
                ],
            )
        )

        if order.status not in (
            Order.Status.PAID,
            Order.Status.ORDER_CONFIRMED,
            Order.Status.ACTIVE_HIRE,
        ):
            return Response(
                {"error": "This order cannot be extended yet."}, status=400
            )

        if not item.rental_end_date:
            return Response(
                {"error": "This item has no rental end date."}, status=400
            )

        additional_days = request.data.get("duration_days")
        new_end_date = request.data.get("new_end_date")
        today = timezone.now().date()

        if additional_days:
            try:
                additional_days = int(additional_days)
            except (TypeError, ValueError):
                return Response(
                    {"error": "duration_days must be an integer"}, status=400
                )
            if additional_days <= 0:
                return Response(
                    {"error": "duration_days must be positive"}, status=400
                )
            parsed = item.rental_end_date + timedelta(days=additional_days)
        elif new_end_date:
            parsed = parse_date(new_end_date)
            if not parsed:
                return Response(
                    {"error": "Invalid date format. Use YYYY-MM-DD"},
                    status=400,
                )
            additional_days = (parsed - item.rental_end_date).days
            if additional_days <= 0:
                return Response(
                    {"error": "New end date must be after the current end date"},
                    status=400,
                )
        else:
            return Response(
                {"error": "duration_days or new_end_date is required"},
                status=400,
            )

        if parsed <= today:
            return Response(
                {"error": "The new end date must be in the future"},
                status=400,
            )

        amount = money(
            item.unit_price * item.quantity * additional_days
        )

        with transaction.atomic():
            extension = RentalExtension.objects.create(
                order_item=item,
                additional_days=additional_days,
                previous_end_date=item.rental_end_date,
                new_end_date=parsed,
                amount=amount,
                currency="NGN",
            )
            payment = Payment.objects.create(
                buyer=request.user,
                amount=amount,
                currency="NGN",
                reference=f"PAY-{uuid.uuid4().hex[:16].upper()}",
                status=Payment.Status.PENDING,
            )
            extension.payment = payment
            extension.save(update_fields=["payment"])

        try:
            data = initialize_transaction(
                email=request.user.email,
                amount_kobo=int(amount * 100),
                reference=payment.reference,
                metadata={"rental_extension_id": extension.id},
                callback_url=settings.PAYSTACK_CALLBACK_URL,
            )
            if not data:
                raise ValueError("Failed to initialize payment gateway")
        except Exception as exc:
            logger.exception("Rental extension payment failed: %s", exc)
            payment.status = Payment.Status.FAILED
            payment.save(update_fields=["status"])
            extension.status = RentalExtension.Status.CANCELLED
            extension.save(update_fields=["status"])
            return Response(
                {"error": "Payment gateway unavailable."}, status=502
            )

        payment.authorization_url = data.get("authorization_url", "")
        payment.paystack_access_code = data.get("access_code", "")
        payment.gateway_response = data
        payment.save(
            update_fields=[
                "authorization_url",
                "paystack_access_code",
                "gateway_response",
            ]
        )

        return Response(
            {
                "message": "Complete payment to extend the rental.",
                "extension_id": extension.id,
                "amount": str(amount),
                "authorization_url": payment.authorization_url,
                "new_end_date": str(parsed),
            },
            status=201,
        )


class OrderActivityListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OrderActivitySerializer

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return OrderActivity.objects.none()
        order_id = self.kwargs['pk']
        user = self.request.user
        queryset = Order.objects.filter(
            Q(buyer=user) | Q(seller=user) | Q(store__user=user)
        )
        if getattr(user, 'is_admin_user', False) or user.is_staff:
            queryset = Order.objects.all()
        order = get_object_or_404(queryset.distinct(), pk=order_id)
        return OrderActivity.objects.filter(
            order=order
        ).select_related("order").order_by('-created_at')


class OrderMarkShippedView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=inline_serializer(
            name="OrderMarkShippedRequest",
            fields={
                "carrier": serializers.CharField(required=True),
                "tracking_id": serializers.CharField(required=True),
            },
        ),
        responses={
            200: inline_serializer(name='OrderMarkShippedResponse', fields={'message': serializers.CharField(), 'status': serializers.CharField(), 'carrier': serializers.CharField(), 'tracking_id': serializers.CharField()}),
            400: inline_serializer(name='OrderMarkShippedError', fields={'error': serializers.CharField()})
        }
    )
    def post(self, request, pk):
        order = get_object_or_404(Order, pk=pk, seller=request.user)

        carrier = (request.data.get("carrier") or "").strip()
        tracking_id = (request.data.get("tracking_id") or "").strip()
        if not carrier or not tracking_id:
            return Response(
                {"error": "carrier and tracking_id are required"},
                status=400,
            )

        try:
            order = transition(
                order,
                "item_dispatched",
                actor=request.user,
                carrier=carrier,
                tracking_id=tracking_id,
                message=(
                    f"Dispatched via {carrier}. Tracking: {tracking_id}."
                ),
            )
        except InvalidTransition as exc:
            return Response({"error": str(exc)}, status=400)

        notify_order_shipped(order)

        return Response({
            "message": "Order marked as shipped",
            "status": order.status,
            "carrier": carrier,
            "tracking_id": tracking_id,
        })


class OrderConfirmReceiptView(APIView):
    """Buyer confirms delivery, completing the order and releasing held funds."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Confirm receipt of an order",
        request=None,
        responses={
            200: inline_serializer(
                name='OrderConfirmReceiptResponse',
                fields={
                    'message': serializers.CharField(),
                    'status': serializers.CharField(),
                },
            ),
            400: inline_serializer(
                name='OrderConfirmReceiptError',
                fields={'error': serializers.CharField()},
            ),
        },
    )
    def post(self, request, pk):
        order = get_object_or_404(Order, pk=pk)
        if order.buyer_id != request.user.id:
            raise exceptions.PermissionDenied(
                "Only the buyer can confirm receipt of this order."
            )

        try:
            order = transition(order, "order_fulfilled", actor=request.user)
        except InvalidTransition as exc:
            return Response({"error": str(exc)}, status=400)

        from apps.notifications.utils import dispatch_tracking_notification
        dispatch_tracking_notification("order_fulfilled", order)

        return Response(
            {"message": "Receipt confirmed", "status": order.status}
        )


class MarketplaceBreakdownView(APIView):
    """
    Marketplace KPIs: buy / hire / lease counts and average order value.
    Query: date_from, date_to (inclusive dates on placed_at, fallback created_at).
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Marketplace breakdown (admin)",
        description="Requires analytics VIEW. Query: date_from, date_to (ISO date).",
        responses={
            200: inline_serializer(
                name='MarketplaceBreakdownResponse',
                fields={
                    'buy_transactions': serializers.IntegerField(),
                    'hire_bookings': serializers.IntegerField(),
                    'lease_contracts': serializers.IntegerField(),
                    'avg_order_value': serializers.FloatField(allow_null=True),
                    'currency': serializers.CharField(),
                }
            )
        }
    )
    def get(self, request):
        if not has_admin_module_permission(
            request.user, AdminModule.ANALYTICS.value, require_manage=False
        ):
            return Response(status=status.HTTP_403_FORBIDDEN)

        df = request.query_params.get("date_from")
        dt = request.query_params.get("date_to")
        qs = Order.objects.all()
        if df:
            d = parse_date(df)
            if d:
                qs = qs.filter(
                    Q(placed_at__date__gte=d)
                    | Q(placed_at__isnull=True, created_at__date__gte=d)
                )
        if dt:
            d = parse_date(dt)
            if d:
                qs = qs.filter(
                    Q(placed_at__date__lte=d)
                    | Q(placed_at__isnull=True, created_at__date__lte=d)
                )

        rows = qs.values("items__purchase_type").annotate(count=Count("id", distinct=True))
        type_counts = {r["items__purchase_type"]: r["count"] for r in rows if r["items__purchase_type"]}
        avg_val = qs.aggregate(avg=Avg("total_amount"))["avg"]

        return Response(
            {
                "buy_transactions": type_counts.get(Order.OrderType.BUY, 0),
                "hire_bookings": type_counts.get(Order.OrderType.HIRE, 0),
                "lease_contracts": type_counts.get(Order.OrderType.LEASE, 0),
                "avg_order_value": float(avg_val) if avg_val is not None else None,
                "currency": "NGN",
            }
        )


class CartView(APIView):
    """Get or clear the cart."""
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={200: CartSerializer})
    def get(self, request):
        cart, _ = Cart.objects.get_or_create(buyer=request.user)
        serializer = CartSerializer(cart, context={'request': request})
        return Response(serializer.data)

    @extend_schema(responses={200: inline_serializer(name='CartClearResponse', fields={'message': serializers.CharField()})})
    def delete(self, request):
        """Clear entire cart."""
        try:
            cart = Cart.objects.get(buyer=request.user)
            cart.items.all().delete()
        except Cart.DoesNotExist:
            pass
        return Response({'message': 'Cart cleared.'})


@extend_schema_view(
    post=extend_schema(operation_id="commerce_cart_items_add", request=CartItemCreateSerializer, responses={201: CartItemSerializer}),
    patch=extend_schema(
        operation_id="commerce_cart_items_update_item",
        request=inline_serializer(name='CartItemUpdateRequest', fields={'quantity': serializers.IntegerField(required=False), 'duration_days': serializers.IntegerField(required=False)}),
        responses={200: CartItemSerializer}
    ),
    delete=extend_schema(operation_id="commerce_cart_items_remove_item", responses={200: inline_serializer(name='CartItemDeleteResponse', fields={'message': serializers.CharField()})}),
)
class CartItemView(APIView):
    """Add, update, or remove cart items."""
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(operation_id="commerce_cart_items_add_item")
    def post(self, request):
        """Add item to cart."""
        cart, _ = Cart.objects.get_or_create(buyer=request.user)
        serializer = CartItemCreateSerializer(
            data=request.data,
            context={'request': request, 'cart': cart}
        )
        serializer.is_valid(raise_exception=True)
        item = serializer.save()
        
        track_item_added_to_cart(request.user, item.listing, item.quantity)

        return Response(
            CartItemSerializer(item, context={'request': request}).data,
            status=status.HTTP_201_CREATED
        )

    @extend_schema(operation_id="commerce_cart_items_update_item_qty")
    def patch(self, request, item_id):
        """Update cart item quantity or duration."""
        cart = get_object_or_404(Cart, buyer=request.user)
        item = get_object_or_404(CartItem, pk=item_id, cart=cart)

        quantity = request.data.get('quantity')
        duration_days = request.data.get('duration_days')

        if quantity is not None:
            if int(quantity) <= 0:
                item.delete()
                return Response({'message': 'Item removed from cart.'})
            item.quantity = quantity

        if duration_days is not None:
            item.duration_days = duration_days

        item.save()
        return Response(
            CartItemSerializer(item, context={'request': request}).data
        )

    @extend_schema(operation_id="commerce_cart_items_remove_item_id")
    def delete(self, request, item_id):
        """Remove specific item from cart."""
        cart = get_object_or_404(Cart, buyer=request.user)
        item = get_object_or_404(CartItem, pk=item_id, cart=cart)
        item.delete()
        return Response({'message': 'Item removed from cart.'})


@extend_schema(
    summary="Checkout and create order(s)",
    description="Convert cart items into order(s) and initialize Paystack payment.",
    request=inline_serializer(
        name="CheckoutRequest",
        fields={
            "cart_item_ids": serializers.ListField(
                child=serializers.IntegerField(),
                help_text="IDs of cart items to checkout",
            ),
            "delivery_detail_id": serializers.IntegerField(
                help_text="ID of saved delivery address",
            ),
            "payment_method": serializers.ChoiceField(
                choices=[("paystack", "Paystack")],
                default="paystack",
            ),
            "terms_accepted": serializers.BooleanField(),
        },
    ),
    responses={
        201: inline_serializer(
            name="CheckoutResponse",
            fields={
                "message": serializers.CharField(),
                "orders": serializers.ListField(
                    child=inline_serializer(
                        name="CheckoutOrder",
                        fields={
                            "order_id": serializers.IntegerField(),
                            "order_number": serializers.CharField(),
                            "total_amount": serializers.CharField(),
                        },
                    ),
                ),
                "payments": serializers.ListField(
                    child=inline_serializer(
                        name="CheckoutPayment",
                        fields={
                            "payment_id": serializers.IntegerField(),
                            "reference": serializers.CharField(),
                            "authorization_url": serializers.URLField(),
                            "amount": serializers.CharField(),
                        },
                    ),
                ),
            },
        ),
    },
)
class CheckoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = CheckoutSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        cart_items = list(
            serializer.validated_data["cart_items"].select_related(
                "listing__store", "delivery_detail", "quote_request"
            )
        )

        missing = [
            item.listing.title
            for item in cart_items
            if item.listing.store_id is None
        ]
        if missing:
            return Response(
                {
                    "error": (
                        "These listings have no store and cannot be checked "
                        f"out: {', '.join(missing)}."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        priced = []
        grand_total = Decimal("0.00")
        for item in cart_items:
            currency = (item.listing.currency or "NGN").upper()
            try:
                subtotal = convert_to_ngn(item.subtotal, currency)
                unit_price_ngn = convert_to_ngn(item.unit_price, currency)
            except CurrencyRateUnavailable as exc:
                return Response(
                    {"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST
                )

            original_unit = Decimal(str(item.unit_price or 0))
            if original_unit > 0:
                exchange_rate = (unit_price_ngn / original_unit).quantize(
                    Decimal("0.00000001")
                )
            else:
                exchange_rate = Decimal("1.00000000")

            delivery_fee = Decimal("0.00")
            total = subtotal + delivery_fee
            grand_total += total
            priced.append(
                (
                    item, subtotal, delivery_fee, total, unit_price_ngn,
                    original_unit, currency, exchange_rate,
                )
            )

        from apps.commerce.models import CheckoutSession, OrderItem

        with transaction.atomic():
            checkout_session = CheckoutSession.objects.create(
                buyer=request.user,
                total_amount=grand_total,
                currency="NGN",
            )

            orders_created = []
            for (
                item, subtotal, delivery_fee, total, unit_price_ngn,
                original_unit, currency, exchange_rate,
            ) in priced:
                store = item.listing.store
                order = Order.objects.create(
                    order_number=f"ORD-{uuid.uuid4().hex[:12].upper()}",
                    buyer=request.user,
                    seller=store.user,
                    store=store,
                    checkout_session=checkout_session,
                    currency="NGN",
                    subtotal=subtotal,
                    delivery_fee=delivery_fee,
                    escrow_fee=Decimal("0.00"),
                    total_amount=total,
                    commission_rate=store.commission_rate,
                    commission_amount=Decimal("0.00"),
                    status=Order.Status.PENDING_PAYMENT,
                    placed_at=timezone.now(),
                )

                rental_start = None
                rental_end = None
                if item.purchase_type in (
                    CartItem.PurchaseType.RENT,
                    CartItem.PurchaseType.LEASE,
                ):
                    rental_start = (
                        item.quote_request.preferred_delivery_date
                        if item.quote_request_id
                        and item.quote_request
                        and item.quote_request.preferred_delivery_date
                        else timezone.now().date()
                    )
                    if item.duration_days:
                        rental_end = rental_start + timedelta(
                            days=item.duration_days
                        )

                OrderItem.objects.create(
                    order=order,
                    listing=item.listing,
                    quote_request=item.quote_request,
                    purchase_type=PURCHASE_TYPE_MAP[item.purchase_type],
                    quantity=item.quantity,
                    unit_price=unit_price_ngn,
                    original_currency=currency,
                    original_unit_price=original_unit,
                    exchange_rate=exchange_rate,
                    delivery_detail=item.delivery_detail,
                    duration_days=item.duration_days,
                    rental_start_date=rental_start,
                    rental_end_date=rental_end,
                )

                OrderActivity.objects.create(
                    order=order,
                    event_type=OrderActivity.EventType.ORDER_PLACED,
                    message="Order placed successfully.",
                )

                transaction.on_commit(
                    lambda order=order: notify_order_placed(order)
                )
                track_order_placed(request.user, order)
                orders_created.append(order)

            payment = Payment.objects.create(
                checkout_session=checkout_session,
                buyer=request.user,
                amount=grand_total,
                currency="NGN",
                reference=f"PAY-{uuid.uuid4().hex[:16].upper()}",
                status=Payment.Status.PENDING,
            )

        try:
            paystack_data = initialize_transaction(
                email=request.user.email,
                amount_kobo=int(grand_total * 100),
                reference=payment.reference,
                metadata={"checkout_session_id": checkout_session.id},
                callback_url=settings.PAYSTACK_CALLBACK_URL,
            )
            if not paystack_data:
                raise ValueError("Failed to initialize payment gateway")
        except Exception as exc:
            logger.exception("Checkout payment initialisation failed: %s", exc)
            payment.status = Payment.Status.FAILED
            payment.gateway_response = {"error": str(exc)}
            payment.save(update_fields=["status", "gateway_response"])
            return Response(
                {
                    "error": "Payment gateway unavailable. Your cart is intact.",
                    "payment_id": payment.id,
                    "retry_url": (
                        f"/commerce/checkout/session/{checkout_session.id}/retry/"
                    ),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        payment.authorization_url = paystack_data.get("authorization_url", "")
        payment.paystack_access_code = paystack_data.get("access_code", "")
        payment.gateway_response = paystack_data
        payment.save(
            update_fields=[
                "authorization_url",
                "paystack_access_code",
                "gateway_response",
            ]
        )
        CartItem.objects.filter(
            pk__in=[item.pk for item in cart_items]
        ).delete()

        return Response(
            {
                "message": f"{len(orders_created)} order(s) created.",
                "orders": [
                    {
                        "order_id": o.id,
                        "order_number": o.order_number,
                        "total_amount": str(o.total_amount),
                    }
                    for o in orders_created
                ],
                "payments": [
                    {
                        "payment_id": payment.id,
                        "reference": payment.reference,
                        "authorization_url": payment.authorization_url,
                        "amount": str(payment.amount),
                    }
                ],
            },
            status=status.HTTP_201_CREATED,
        )


class RetryPaymentView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Retry Payment for an existing checkout session",
        request=None,
        responses={200: inline_serializer(name='RetryPaymentResponse', fields={'authorization_url': serializers.URLField()})}
    )
    def post(self, request, session_id):
        from apps.commerce.models import CheckoutSession, Payment
        session = get_object_or_404(CheckoutSession, id=session_id, buyer=request.user)
        payment = get_object_or_404(Payment, checkout_session=session, buyer=request.user)
        
        if payment.status == Payment.Status.SUCCESS:
            return Response({"message": "Payment already successful"}, status=status.HTTP_400_BAD_REQUEST)

        # Generate new reference
        reference = f"PAY-{uuid.uuid4().hex[:16].upper()}"
        
        paystack_data = initialize_transaction(
            email=request.user.email,
            amount_kobo=int(session.total_amount * 100),
            reference=reference,
            metadata={'checkout_session_id': session.id},
            callback_url=settings.PAYSTACK_CALLBACK_URL,
        )

        if not paystack_data:
            return Response({"error": "Failed to re-initialize payment gateway."}, status=status.HTTP_400_BAD_REQUEST)

        payment.reference = reference
        payment.authorization_url = paystack_data.get('authorization_url', '')
        payment.paystack_access_code = paystack_data.get('access_code', '')
        payment.gateway_response = paystack_data
        payment.save(update_fields=['reference', 'authorization_url', 'paystack_access_code', 'gateway_response'])

        return Response({"authorization_url": payment.authorization_url})




class PaymentVerifyView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        responses={
            200: inline_serializer(name='PaymentVerifyResponse', fields={'status': serializers.CharField(), 'message': serializers.CharField(), 'checkout_session_id': serializers.IntegerField(required=False)}),
            503: inline_serializer(name='PaymentVerifyUnavailable', fields={'status': serializers.CharField(), 'message': serializers.CharField()})
        }
    )
    def get(self, request, reference):
        payment = get_object_or_404(
            Payment, reference=reference, buyer=request.user)

        if payment.status == Payment.Status.SUCCESS:
            return Response({
                'status': 'success',
                'message': 'Payment confirmed.',
                'checkout_session_id': payment.checkout_session_id,
            })
        if payment.status in (Payment.Status.FAILED, Payment.Status.REFUNDED):
            return Response({
                'status': 'failed',
                'message': 'Payment was not completed.',
            })

        paystack_data = verify_transaction(reference)
        if paystack_data is None:
            return Response(
                {
                    'status': 'unknown',
                    'message': 'Gateway unavailable. Try again shortly.',
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if paystack_data.get('status') == 'success':
            return Response({
                'status': 'pending_confirmation',
                'message': 'Awaiting webhook confirmation.',
            })

        return Response({
            'status': 'pending',
            'message': 'Payment not completed.',
        })


class DisputeListCreateView(generics.ListCreateAPIView):
    """Buyers can open a dispute. All users can list their related disputes."""
    serializer_class = DisputeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Dispute.objects.none()
        user = self.request.user
        if getattr(user, 'is_admin_user', False):
            return Dispute.objects.all()
        return Dispute.objects.filter(Q(buyer=user) | Q(order__seller=user))

    def perform_create(self, serializer):
        with transaction.atomic():
            dispute = serializer.save()
            # Freeze vendor funds
            from apps.financials.models import VendorEarning
            VendorEarning.objects.filter(order=dispute.order).update(is_disputed=True)

            OrderActivity.objects.create(
                order=dispute.order,
                event_type=OrderActivity.EventType.OTHER,
                message=f"A dispute has been opened: {dispute.reason}"
            )


class DisputeDetailView(generics.RetrieveAPIView):
    serializer_class = DisputeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if getattr(user, 'is_admin_user', False):
            return Dispute.objects.all()
        return Dispute.objects.filter(Q(buyer=user) | Q(order__seller=user))


class DisputeActionView(APIView):
    """Admin-only: resolve or refund a dispute."""

    permission_classes = [permissions.IsAuthenticated, HasAdminModulePermission]
    admin_module = AdminModule.SUPPORTS
    admin_require_manage = True

    @extend_schema(
        request=DisputeResolutionSerializer,
        responses={200: inline_serializer(
            name='DisputeActionResponse', fields={'message': serializers.CharField()}
        )}
    )
    def post(self, request, pk):
        from apps.commerce.services.refunds import RefundError, request_refund
        from apps.financials.models import VendorEarning

        dispute = get_object_or_404(Dispute, pk=pk)
        serializer = DisputeResolutionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data['action']
        notes = serializer.validated_data['resolution_notes']

        earning = VendorEarning.objects.filter(order=dispute.order).first()

        if action == 'resolve':
            if earning:
                earning.is_disputed = False
                earning.save(update_fields=['is_disputed'])
            dispute.status = Dispute.Status.RESOLVED
            message = "Dispute resolved. Funds released to vendor escrow."

        elif action == 'refund':
            payment = Payment.objects.filter(
                checkout_session=dispute.order.checkout_session
            ).first()
            if payment is None:
                return Response(
                    {'error': 'No payment is linked to this order.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if earning:
                earning.is_disputed = True
                earning.save(update_fields=['is_disputed'])
            try:
                request_refund(
                    payment,
                    amount=payment.amount,
                    reason=notes or dispute.reason,
                    actor=request.user,
                )
            except RefundError as exc:
                return Response(
                    {'error': str(exc)},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            dispute.status = Dispute.Status.UNDER_REVIEW
            message = (
                "Refund requested. The dispute closes when the gateway confirms."
            )

        else:
            return Response(
                {'error': 'Invalid action.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        dispute.resolution_notes = notes
        dispute.resolved_at = timezone.now() if action == 'resolve' else None
        dispute.save(
            update_fields=['status', 'resolution_notes', 'resolved_at'])

        OrderActivity.objects.create(
            order=dispute.order,
            event_type=OrderActivity.EventType.OTHER,
            message=message,
        )
        return Response({'message': message})


class RecentSalesView(generics.ListAPIView):
    """
    Returns recent paid or fulfilled orders for the vendor's store.
    Used for the vendor dashboard 'Recent Sales' widget.
    """
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if not hasattr(user, 'store'):
            return Order.objects.none()
            
        from apps.commerce.constants import SALES_STATUSES

        return Order.objects.filter(
            store=user.store,
            status__in=SALES_STATUSES
        ).select_related(
            "buyer"
        ).order_by("-created_at")[:10]  # Return top 10 recent sales


class OrderTrackingDetailView(generics.RetrieveUpdateAPIView):
    """
    Returns the current status of the order plus the full chronological activity timeline.
    Accessible only to the buyer of that order, the seller, or any admin.
    Can be PATCHed by the seller to update tracking details.
    """
    serializer_class = OrderTrackingDetailSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        pk_or_num = self.kwargs.get("pk_or_num")
        queryset = Order.objects.select_related(
            "buyer", "seller", "store"
        ).prefetch_related("items__listing", "activities", "disputes")
        if str(pk_or_num).isdigit():
            order = get_object_or_404(queryset, pk=pk_or_num)
        else:
            order = get_object_or_404(queryset, order_number=pk_or_num)
        
        user = self.request.user
        is_buyer = order.buyer == user
        is_seller = order.seller == user or (order.store and order.store.user == user)
        is_admin = getattr(user, 'is_admin_user', False) or user.is_staff

        if not (is_buyer or is_seller or is_admin):
            raise exceptions.PermissionDenied("You do not have permission to access this order's tracking details.")
        return order

    def patch(self, request, *args, **kwargs):
        order = self.get_object()
        user = request.user
        is_seller = order.seller == user or (order.store and order.store.user == user)
        if not is_seller:
            raise exceptions.PermissionDenied("Only the seller of this order can update the tracking details.")

        tracking_id = request.data.get("tracking_id")
        carrier = request.data.get("carrier")

        if tracking_id is not None:
            order.tracking_id = tracking_id
        if carrier is not None:
            order.delivery_carrier = carrier
            if not isinstance(order.extra, dict):
                order.extra = {}
            order.extra["carrier"] = carrier

        order.save()

        serializer = self.get_serializer(order)
        return Response(serializer.data, status=status.HTTP_200_OK)


class BuyerMyOrdersListView(generics.ListAPIView):
    """
    Returns all orders placed by the authenticated buyer, with a lightweight tracking summary per order.
    """
    serializer_class = OrderListTrackingSummarySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Order.objects.none()
        return Order.objects.filter(buyer=self.request.user).select_related(
            "store", "buyer", "seller"
        ).prefetch_related(
            "items__listing", "activities"
        ).order_by("-created_at")


class SellerStoreOrdersListView(generics.ListAPIView):
    """
    Returns all orders where the purchased listing belongs to the authenticated user's store.
    """
    serializer_class = OrderListTrackingSummarySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Order.objects.none()
        return Order.objects.filter(
            Q(seller=self.request.user) | Q(store__user=self.request.user)
        ).select_related(
            "store", "buyer", "seller"
        ).prefetch_related(
            "items__listing", "activities"
        ).distinct().order_by("-created_at")


class OrderTrackingUpdateView(generics.CreateAPIView):
    """
    Allows the seller to advance the order status and append an OrderActivity event.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OrderTrackingDetailSerializer

    def post(self, request, pk_or_num):
        if str(pk_or_num).isdigit():
            order = get_object_or_404(Order, pk=pk_or_num)
        else:
            order = get_object_or_404(Order, order_number=pk_or_num)

        user = request.user
        is_seller = order.seller == user or (order.store and order.store.user == user)
        if not is_seller:
            raise exceptions.PermissionDenied("Only the seller of this order can update the tracking status.")

        event = request.data.get("event")
        note = request.data.get("note", "")

        # Validate event is a valid seller event
        seller_events = [
            'order_confirmed', 'item_dispatched', 'in_transit',
            'delivered', 'hire_started', 'hire_ended', 'item_returned',
            'order_fulfilled', 'order_cancelled'
        ]
        if event not in seller_events:
            return Response(
                {"error": f"Invalid seller-triggered tracking event. Allowed events are: {', '.join(seller_events)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            order = transition(
                order,
                event,
                actor=request.user,
                message=note or None,
                carrier=request.data.get("carrier"),
                tracking_id=request.data.get("tracking_id"),
                reason=request.data.get("reason"),
            )
        except InvalidTransition as exc:
            return Response(
                {"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )

        # Trigger notification
        from apps.notifications.utils import dispatch_tracking_notification
        dispatch_tracking_notification(event, order)

        serializer = self.get_serializer(order)
        return Response(serializer.data, status=status.HTTP_200_OK)


class BuyerSentQuotesView(generics.ListAPIView):
    """
    Returns all QuoteRequest objects where buyer = request.user, paginated, ordered by most recent first.
    """
    serializer_class = QuoteRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return QuoteRequest.objects.none()
        return QuoteRequest.objects.filter(buyer=self.request.user).order_by("-created_at")


class SellerReceivedQuotesView(generics.ListAPIView):
    """
    Returns all QuoteRequest objects where the associated listing belongs to request.user's store, paginated, ordered by most recent first.
    """
    serializer_class = QuoteRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return QuoteRequest.objects.none()
        return QuoteRequest.objects.filter(
            Q(store__user=self.request.user) | Q(listing__store__user=self.request.user)
        ).distinct().order_by("-created_at")


class OrderInvoicePDFView(APIView):
    """
    Generates and returns a beautifully-styled PDF invoice for a specific order.
    Access restricted to buyer, seller, or admin/staff.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={200: OpenApiTypes.BINARY})
    def get(self, request, pk, *args, **kwargs):
        import io
        from django.http import HttpResponse
        from django.shortcuts import get_object_or_404
        from rest_framework.exceptions import PermissionDenied
        
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch

        order = get_object_or_404(Order, pk=pk)

        # Access check: Buyer, Seller, or Admin
        if not (request.user == order.buyer or request.user == order.seller or request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied("You do not have permission to access this invoice.")

        # Create memory buffer
        buffer = io.BytesIO()

        # Create ReportLab Document setup
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=36,
            leftMargin=36,
            topMargin=36,
            bottomMargin=36
        )

        story = []

        # Styles setup
        styles = getSampleStyleSheet()
        
        title_style = ParagraphStyle(
            'InvoiceTitle',
            parent=styles['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=22,
            leading=26,
            textColor=colors.HexColor('#002B49')
        )
        
        company_style = ParagraphStyle(
            'CompanyHeader',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=16,
            leading=20,
            textColor=colors.HexColor('#002B49')
        )
        
        header_style = ParagraphStyle(
            'InvoiceHeader',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=9,
            leading=12,
            textColor=colors.HexColor('#555555')
        )
        
        body_style = ParagraphStyle(
            'InvoiceBody',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=9,
            leading=13,
            textColor=colors.HexColor('#333333')
        )
        
        table_header_style = ParagraphStyle(
            'TableHeader',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=9,
            leading=11,
            textColor=colors.white
        )

        # 1. Page Header (Branding & Title side-by-side)
        header_data = [
            [
                Paragraph("HARBOUR HUB", company_style),
                Paragraph("INVOICE", ParagraphStyle('InvoiceText', parent=title_style, alignment=2)) # Align Right
            ],
            [
                Paragraph("Email: support@harbourhubglobal.com<br/>Web: www.harbourhubglobal.com", body_style),
                Paragraph(f"<b>Invoice #:</b> {order.order_number}<br/><b>Date:</b> {(order.placed_at or order.created_at).strftime('%Y-%m-%d %H:%M') if (order.placed_at or order.created_at) else 'N/A'}", ParagraphStyle('InvoiceMetaText', parent=body_style, alignment=2))
            ]
        ]
        
        header_table = Table(header_data, colWidths=[3.5*inch, 3.5*inch])
        header_table.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('TOPPADDING', (0,0), (-1,-1), 4),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 15))

        # Divider line
        divider_data = [[""]]
        divider = Table(divider_data, colWidths=[7.0*inch])
        divider.setStyle(TableStyle([
            ('LINEABOVE', (0,0), (-1,-1), 1.5, colors.HexColor('#002B49')),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
        ]))
        story.append(divider)
        story.append(Spacer(1, 15))

        # 2. Transaction Information Block (Order Type, Status)
        # 2. Transaction Information Block (Status, Date)
        txn_data = [
            [
                Paragraph("<b>Status:</b>", header_style),
                Paragraph("<b>Date Placed:</b>", header_style),
                Paragraph("<b>Payment Currency:</b>", header_style),
            ],
            [
                Paragraph(order.get_status_display(), body_style),
                Paragraph(order.placed_at.strftime("%B %d, %Y") if order.placed_at else 'N/A', body_style),
                Paragraph(order.currency, body_style),
            ]
        ]
        txn_table = Table(txn_data, colWidths=[2.33*inch, 2.33*inch, 2.34*inch])
        txn_table.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#EEEEEE')),
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F9F9F9')),
        ]))
        story.append(txn_table)
        story.append(Spacer(1, 15))

        # 3. Buyer & Seller Information Block
        billing_data = [
            [
                Paragraph("<b>Billed To (Buyer):</b>", header_style),
                Paragraph("<b>Sold By (Seller):</b>", header_style),
            ],
            [
                Paragraph(f"{order.buyer.full_name or 'N/A'}<br/>{order.buyer.email}<br/>Phone: {order.buyer.phone or 'N/A'}", body_style),
                Paragraph(f"{order.store.name if order.store else order.seller.company or order.seller.full_name or 'N/A'}<br/>{order.seller.email}<br/>Phone: {order.seller.phone or 'N/A'}", body_style),
            ]
        ]
        billing_table = Table(billing_data, colWidths=[3.5*inch, 3.5*inch])
        billing_table.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('TOPPADDING', (0,0), (-1,-1), 4),
        ]))
        story.append(billing_table)
        story.append(Spacer(1, 15))

        # 4. Delivery Address block (if available)
        if order.delivery_address:
            delivery_data = [
                [Paragraph("<b>Delivery Information:</b>", header_style)],
                [Paragraph(f"Contact Name: {order.delivery_contact_name or 'N/A'}<br/>Contact Phone: {order.delivery_contact_phone or 'N/A'}<br/>Address: {order.delivery_address}", body_style)]
            ]
            delivery_table = Table(delivery_data, colWidths=[7.0*inch])
            delivery_table.setStyle(TableStyle([
                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                ('TOPPADDING', (0,0), (-1,-1), 4),
            ]))
            story.append(delivery_table)
            story.append(Spacer(1, 15))



        # 6. Itemized Marketplace Table
        item_table_data = [
            [
                Paragraph("Item Description / Listing", table_header_style),
                Paragraph("Amount", table_header_style)
            ],
            [
                Paragraph(order.items.first().listing.title if order.items.exists() and order.items.first().listing else "Marketplace Item / Order Transaction", body_style),
                Paragraph(f"{order.currency} {order.subtotal or order.total_amount:,.2f}", body_style)
            ]
        ]
        item_table = Table(item_table_data, colWidths=[4.0*inch, 1.2*inch, 1.8*inch])
        item_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#002B49')),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BOTTOMPADDING', (0,0), (-1,0), 6),
            ('TOPPADDING', (0,0), (-1,0), 6),
            ('BOTTOMPADDING', (0,1), (-1,-1), 6),
            ('TOPPADDING', (0,1), (-1,-1), 6),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#DDDDDD')),
        ]))
        story.append(item_table)
        story.append(Spacer(1, 15))

        # 7. Financial Breakdown Table
        summary_data = [
            [Paragraph("Subtotal:", header_style), Paragraph(f"{order.currency} {order.subtotal or 0.00:,.2f}", body_style)],
            [Paragraph("Escrow Fee:", header_style), Paragraph(f"{order.currency} {order.escrow_fee or 0.00:,.2f}", body_style)],
            [Paragraph("Delivery Fee:", header_style), Paragraph(f"{order.currency} {order.delivery_fee or 0.00:,.2f}", body_style)],
            [
                Paragraph("<b>Total Amount:</b>", ParagraphStyle('TotalLabel', parent=header_style, fontSize=10)),
                Paragraph(f"<b>{order.currency} {order.total_amount:,.2f}</b>", ParagraphStyle('TotalVal', parent=body_style, fontSize=10))
            ]
        ]
        summary_table = Table(summary_data, colWidths=[1.5*inch, 2.0*inch], hAlign='RIGHT')
        summary_table.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'RIGHT'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ('TOPPADDING', (0,0), (-1,-1), 3),
            ('LINEBELOW', (0,-1), (-1,-1), 1, colors.HexColor('#002B49')),
            ('LINEABOVE', (0,-1), (-1,-1), 1, colors.HexColor('#002B49')),
        ]))
        story.append(summary_table)
        story.append(Spacer(1, 30))

        # 8. Footer Notes
        footer_style = ParagraphStyle(
            'InvoiceFooter',
            parent=styles['Normal'],
            fontName='Helvetica-Oblique',
            fontSize=8,
            leading=10,
            textColor=colors.HexColor('#777777'),
            alignment=1 # Center
        )
        story.append(Paragraph("Thank you for choosing Harbour Hub. Your digital marketplace for industrial equipment.", footer_style))
        story.append(Spacer(1, 5))
        story.append(Paragraph("This is a system generated document. No signature is required.", footer_style))

        # Build PDF
        doc.build(story)

        # Get value and write to response
        pdf = buffer.getvalue()
        buffer.close()

        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="invoice_{order.order_number}.pdf"'
        return response
