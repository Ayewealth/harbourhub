import uuid
import hmac
import hashlib
import requests

from decimal import Decimal
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.utils.dateparse import parse_date
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample, inline_serializer
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
from apps.admin_panel.auth import has_admin_module_permission
from apps.admin_panel.constants import AdminModule
from apps.notifications.utils import notify_order_cancelled, notify_order_placed, notify_order_shipped, notify_quote_received, notify_quote_responded
from apps.analytics.posthog_utils import (
    track_quote_requested, track_order_placed, 
    track_payment_success, track_payment_failed,
    track_item_added_to_cart
)


from .filters import OrderFilter, QuoteRequestFilter
from .models import Cart, CartItem, Order, OrderActivity, Payment, QuoteRequest, Dispute
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
        user = self.request.user
        qs = QuoteRequest.objects.select_related(
            "listing", "buyer", "store"
        ).order_by("-created_at")
        if user.is_staff and self.request.query_params.get("all") == "true":
            return qs
        return qs.filter(Q(buyer=user) | Q(listing__user=user))

    def perform_create(self, serializer):
        quote = serializer.save(buyer=self.request.user)
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


@extend_schema(
    summary="Quote action",
    examples=[
        OpenApiExample(
            "Respond to quote",
            value={"action": "respond"},
            request_only=True,
        ),
        OpenApiExample(
            "Cancel quote",
            value={"action": "cancel"},
            request_only=True,
        ),
        OpenApiExample(
            "Convert quote",
            value={"action": "convert"},
            request_only=True,
        ),
    ],
)
class QuoteRequestActionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

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

    @transaction.atomic
    def post(self, request, pk):
        quote = get_object_or_404(
            QuoteRequest,
            pk=pk,
            buyer=request.user,
            status=QuoteRequest.Status.RESPONDED
        )

        cart, _ = Cart.objects.get_or_create(buyer=request.user)

        # Use vendor's counter-offer price, fallback to listing price
        quoted_price = request.data.get('quoted_price') or quote.vendor_price or quote.listing.price

        CartItem.objects.update_or_create(
            cart=cart,
            listing=quote.listing,
            purchase_type=quote.purchase_type,
            defaults={
                'quantity': quote.quantity,
                'unit_price': quoted_price,
                'store': quote.store,
                'duration_days': quote.duration_days,
                'quote_request': quote,
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
                'unit_price': str(quoted_price),
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
                    "order_type": "buy",
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
                    "order_type": "hire",
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
class OrderListCreateView(generics.ListCreateAPIView):
    filter_backends = [DjangoFilterBackend]
    filterset_class = OrderFilter
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return OrderCreateSerializer
        return OrderSerializer

    def get_queryset(self):
        user = self.request.user
        qs = Order.objects.select_related(
            "buyer", "seller", "listing", "store"
        ).order_by("-created_at")
        if user.is_staff and self.request.query_params.get("all") == "true":
            return qs
        return qs.filter(Q(buyer=user) | Q(seller=user))


class OrderDetailView(generics.RetrieveAPIView):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return Order.objects.filter(
            Q(buyer=user) | Q(seller=user)
        ).select_related("buyer", "seller", "listing", "store")

    def post(self, request, pk=None):
        """Cancel an order"""
        order = self.get_object()
        if request.user not in (order.buyer, order.seller):
            return Response({'error': 'Permission denied'}, status=403)
        if order.status not in (Order.Status.DRAFT, Order.Status.PENDING_PAYMENT):
            return Response({'error': 'Order cannot be cancelled at this stage'}, status=400)
        order.status = Order.Status.CANCELLED
        order.save(update_fields=['status'])

        notify_order_cancelled(order, cancelled_by=request.user)

        # Log activity
        OrderActivity.objects.create(
            order=order,
            event_type=OrderActivity.EventType.ORDER_CANCELLED,
            message="Order has been cancelled."
        )
        return Response({'message': 'Order cancelled successfully'})


@extend_schema_view(
    post=extend_schema(
        summary="Extend order rental period",
        request=inline_serializer(
            name="ExtendRentalRequest",
            fields={
                "new_end_date": serializers.DateField(
                    help_text="New rental end date (YYYY-MM-DD)"),
                "duration_days": serializers.IntegerField(
                    required=False,
                    help_text="Alternative: number of days to extend from current end date"),
            },
        ),
    ),
    examples=[
        OpenApiExample(
            "Extend by date",
            value={"new_end_date": "2026-04-20"}
        ),
        OpenApiExample(
            "Extend by days",
            value={"duration_days": 7}
        ),
    ]
)
class OrderExtendRentalView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            order = Order.objects.get(
                pk=pk, buyer=request.user,
                order_type__in=[Order.OrderType.HIRE, Order.OrderType.LEASE]
            )
        except Order.DoesNotExist:
            return Response({'error': 'Order not found'}, status=404)

        from django.utils.dateparse import parse_date
        from datetime import timedelta

        duration_days = request.data.get('duration_days')
        new_end_date = request.data.get('new_end_date')

        if duration_days:
            try:
                duration_days = int(duration_days)
            except (TypeError, ValueError):
                return Response({'error': 'duration_days must be an integer'}, status=400)
            if duration_days <= 0:
                return Response({'error': 'duration_days must be positive'}, status=400)
            base_date = order.rental_end_date or timezone.now().date()
            parsed = base_date + timedelta(days=duration_days)
        elif new_end_date:
            parsed = parse_date(new_end_date)
            if not parsed:
                return Response({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=400)
        else:
            return Response({'error': 'new_end_date or duration_days is required'}, status=400)

        if order.rental_end_date and parsed <= order.rental_end_date:
            return Response({'error': 'New end date must be after current end date'}, status=400)

        order.rental_end_date = parsed
        order.rental_duration_days = (parsed - order.rental_start_date).days if order.rental_start_date else None
        order.save(update_fields=['rental_end_date', 'rental_duration_days'])

        OrderActivity.objects.create(
            order=order,
            event_type=OrderActivity.EventType.RENTAL_EXTENDED,
            message=f"Rental extended to {parsed}."
        )

        return Response({
            'message': 'Rental extended successfully',
            'new_end_date': str(parsed),
            'rental_days_total': order.rental_days_total,
        })


class OrderActivityListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OrderActivitySerializer

    def get_queryset(self):
        order_id = self.kwargs['pk']
        user = self.request.user
        order = get_object_or_404(
            Order, pk=order_id,
            **{'buyer': user} if not user.is_staff else {}
        )
        return OrderActivity.objects.filter(
            order=order
        ).order_by('-created_at')


class OrderMarkShippedView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        order = get_object_or_404(
            Order,
            pk=pk,
            seller=request.user
        )

        if order.status != Order.Status.PAID:
            return Response(
                {"error": "Only paid orders can be shipped"},
                status=400
            )

        order.status = Order.Status.FULFILLED
        order.save(update_fields=["status"])

        OrderActivity.objects.create(
            order=order,
            event_type=OrderActivity.EventType.SHIPPED,
            message="Order has been shipped"
        )

        notify_order_shipped(order)

        return Response({"message": "Order marked as shipped"})


class MarketplaceBreakdownView(APIView):
    """
    Marketplace KPIs: buy / hire / lease counts and average order value.
    Query: date_from, date_to (inclusive dates on placed_at, fallback created_at).
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Marketplace breakdown (admin)",
        description="Requires analytics VIEW. Query: date_from, date_to (ISO date).",
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

        rows = qs.values("order_type").annotate(count=Count("id"))
        type_counts = {r["order_type"]: r["count"] for r in rows}
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

    def get(self, request):
        cart, _ = Cart.objects.get_or_create(buyer=request.user)
        serializer = CartSerializer(cart, context={'request': request})
        return Response(serializer.data)

    def delete(self, request):
        """Clear entire cart."""
        try:
            cart = Cart.objects.get(buyer=request.user)
            cart.items.all().delete()
        except Cart.DoesNotExist:
            pass
        return Response({'message': 'Cart cleared.'})


class CartItemView(APIView):
    """Add, update, or remove cart items."""
    permission_classes = [permissions.IsAuthenticated]

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

    def delete(self, request, item_id):
        """Remove specific item from cart."""
        cart = get_object_or_404(Cart, buyer=request.user)
        item = get_object_or_404(CartItem, pk=item_id, cart=cart)
        item.delete()
        return Response({'message': 'Item removed from cart.'})


class CheckoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    ESCROW_RATE = Decimal('0.05')
    DELIVERY_FEE = Decimal('250.00')

    @transaction.atomic
    def post(self, request):
        serializer = CheckoutSerializer(
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)

        cart_items = serializer.validated_data['cart_items']
        delivery_detail = getattr(serializer, 'delivery_detail', None)

        from collections import defaultdict
        store_groups = defaultdict(list)
        for item in cart_items:
            store_key = item.store_id or 'no_store'
            store_groups[store_key].append(item)

        orders_created = []
        payments_created = []

        for store_key, items in store_groups.items():
            subtotal = sum(item.subtotal for item in items)
            escrow_fee = (subtotal * self.ESCROW_RATE).quantize(
                Decimal('0.01'))
            total = subtotal + self.DELIVERY_FEE + escrow_fee

            first_item = items[0]
            order_type_map = {
                CartItem.PurchaseType.BUY: Order.OrderType.BUY,
                CartItem.PurchaseType.RENT: Order.OrderType.HIRE,
                CartItem.PurchaseType.LEASE: Order.OrderType.LEASE,
            }
            order_type = order_type_map.get(
                first_item.purchase_type, Order.OrderType.BUY)

            seller = first_item.listing.user
            delivery_address = ''
            delivery_contact_name = ''
            delivery_contact_phone = ''

            if delivery_detail:
                delivery_address = (
                    f"{delivery_detail.address}, "
                    f"{delivery_detail.city}, {delivery_detail.state}"
                )
                delivery_contact_name = delivery_detail.contact_person
                delivery_contact_phone = delivery_detail.phone

            order = Order.objects.create(
                order_number=f"ORD-{uuid.uuid4().hex[:12].upper()}",
                order_type=order_type,
                buyer=request.user,
                seller=seller,
                listing=first_item.listing,
                store=first_item.store,
                currency='NGN',
                subtotal=subtotal,
                delivery_fee=self.DELIVERY_FEE,
                escrow_fee=escrow_fee,
                total_amount=total,
                status=Order.Status.PENDING_PAYMENT,
                placed_at=timezone.now(),
                delivery_address=delivery_address,
                delivery_contact_name=delivery_contact_name,
                delivery_contact_phone=delivery_contact_phone,
            )

            if first_item.purchase_type in [CartItem.PurchaseType.RENT, CartItem.PurchaseType.LEASE]:
                rental_start = first_item.quote_request.preferred_delivery_date if first_item.quote_request_id and first_item.quote_request and first_item.quote_request.preferred_delivery_date else timezone.now().date()
                order.rental_start_date = rental_start
                if first_item.duration_days:
                    order.rental_end_date = rental_start + timedelta(days=first_item.duration_days)
                    order.rental_duration_days = first_item.duration_days
                order.save(update_fields=['rental_start_date', 'rental_end_date', 'rental_duration_days'])

            OrderActivity.objects.create(
                order=order,
                event_type=OrderActivity.EventType.ORDER_PLACED,
                message="Order placed successfully."
            )

            notify_order_placed(order)
            track_order_placed(request.user, order)

            orders_created.append(order)

            # Use paystack.py client
            reference = f"PAY-{uuid.uuid4().hex[:16].upper()}"
            payment = Payment.objects.create(
                order=order,
                buyer=request.user,
                amount=total,
                currency='NGN',
                reference=reference,
                status=Payment.Status.PENDING,
            )

            paystack_data = initialize_transaction(
                email=request.user.email,
                amount_kobo=int(total * 100),
                reference=reference,
                metadata={'order_id': order.id},
                callback_url=settings.PAYSTACK_CALLBACK_URL,
            )

            if paystack_data:
                payment.authorization_url = paystack_data.get(
                    'authorization_url', '')
                payment.paystack_access_code = paystack_data.get(
                    'access_code', '')
                payment.gateway_response = paystack_data
                payment.save(update_fields=[
                    'authorization_url',
                    'paystack_access_code',
                    'gateway_response'
                ])

            payments_created.append(payment)

        # Remove checked out items from cart
        cart_items.delete()

        return Response({
            'message': f'{len(orders_created)} order(s) created.',
            'orders': [
                {
                    'order_id': o.id,
                    'order_number': o.order_number,
                    'total_amount': str(o.total_amount),
                }
                for o in orders_created
            ],
            'payments': [
                {
                    'payment_id': p.id,
                    'reference': p.reference,
                    'authorization_url': p.authorization_url,
                    'amount': str(p.amount),
                }
                for p in payments_created
            ],
        }, status=status.HTTP_201_CREATED)


class PaymentVerifyView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def get(self, request, reference):
        payment = get_object_or_404(
            Payment, reference=reference, buyer=request.user)

        if payment.status == Payment.Status.SUCCESS:
            return Response({
                'status': 'success',
                'message': 'Payment already verified.',
                'order_id': payment.order_id,
            })

        # Use paystack.py client
        paystack_data = verify_transaction(reference)

        if paystack_data and paystack_data.get('status') == 'success':
            payment.status = Payment.Status.SUCCESS
            payment.paid_at = timezone.now()
            payment.gateway_response = paystack_data
            payment.save(update_fields=[
                'status', 'paid_at', 'gateway_response'])

            order = payment.order
            order.status = Order.Status.PAID
            order.save(update_fields=['status'])

            OrderActivity.objects.create(
                order=order,
                event_type=OrderActivity.EventType.PAYMENT_CONFIRMED,
                message="Payment confirmed. Funds held in escrow."
            )

            track_payment_success(request.user, order)

            return Response({
                'status': 'success',
                'message': 'Payment verified successfully.',
                'order_id': payment.order_id,
            })

        payment.status = Payment.Status.FAILED
        payment.save(update_fields=['status'])
        
        track_payment_failed(request.user, payment.order, "Verification failed or cancelled")
        
        return Response(
            {'status': 'failed', 'message': 'Payment not successful.'},
            status=status.HTTP_400_BAD_REQUEST
        )


class DisputeListCreateView(generics.ListCreateAPIView):
    """Buyers can open a dispute. All users can list their related disputes."""
    serializer_class = DisputeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
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
    """Admin-only: Resolve or Refund a dispute."""
    permission_classes = [permissions.IsAuthenticated] # Should be IsAdmin

    def post(self, request, pk):
        dispute = get_object_or_404(Dispute, pk=pk)
        serializer = DisputeResolutionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        action = serializer.validated_data['action']
        notes = serializer.validated_data['resolution_notes']

        from apps.financials.models import VendorEarning, VendorWallet, WalletTransaction

        with transaction.atomic():
            earning = VendorEarning.objects.get(order=dispute.order)

            if action == 'resolve':
                dispute.status = Dispute.Status.RESOLVED
                earning.is_disputed = False
                earning.save(update_fields=['is_disputed'])
                message = "Dispute resolved. Funds released to vendor escrow."

            elif action == 'refund':
                dispute.status = Dispute.Status.REFUNDED
                earning.status = VendorEarning.Status.REVERSED
                earning.is_disputed = False
                earning.save(update_fields=['status', 'is_disputed'])

                # Reverse wallet credit
                wallet = VendorWallet.objects.get(user=earning.vendor)
                if earning.status == VendorEarning.Status.PENDING:
                    wallet.pending_balance -= earning.net_amount
                    wallet.save(update_fields=['pending_balance'])
                else:
                    wallet.available_balance -= earning.net_amount
                    wallet.save(update_fields=['available_balance'])

                WalletTransaction.objects.create(
                    wallet=wallet,
                    transaction_type=WalletTransaction.Type.REFUND,
                    amount=-earning.net_amount,
                    description=f"Reversed earning due to dispute refund on order {dispute.order.order_number}",
                    reference_id=str(dispute.id)
                )

                dispute.order.status = Order.Status.CANCELLED # or REFUNDED
                dispute.order.save(update_fields=['status'])
                message = "Dispute resolved with refund. Vendor funds reversed."

            dispute.resolution_notes = notes
            dispute.resolved_at = timezone.now()
            dispute.save()

            OrderActivity.objects.create(
                order=dispute.order,
                event_type=OrderActivity.EventType.OTHER,
                message=message
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
            
        return Order.objects.filter(
            store=user.store,
            status__in=[Order.Status.PAID, Order.Status.FULFILLED]
        ).select_related(
            "buyer", "listing"
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
        if str(pk_or_num).isdigit():
            order = get_object_or_404(Order, pk=pk_or_num)
        else:
            order = get_object_or_404(Order, order_number=pk_or_num)
        
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
        return Order.objects.filter(buyer=self.request.user).order_by("-created_at")


class SellerStoreOrdersListView(generics.ListAPIView):
    """
    Returns all orders where the purchased listing belongs to the authenticated user's store.
    """
    serializer_class = OrderListTrackingSummarySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Order.objects.filter(
            Q(seller=self.request.user) | Q(store__user=self.request.user)
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
            'delivered', 'item_returned', 'order_fulfilled', 'order_cancelled'
        ]
        if event not in seller_events:
            return Response(
                {"error": f"Invalid seller-triggered tracking event. Allowed events are: {', '.join(seller_events)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Enforce state machine rules
        VALID_TRANSITIONS = {
            "pending_payment": [("order_cancelled", "cancelled")],
            "paid": [("order_confirmed", "order_confirmed")],
            "order_confirmed": [("item_dispatched", "item_dispatched")],
            "item_dispatched": [("in_transit", "in_transit")],
            "in_transit": [("delivered", "delivered")],
            "delivered": [("order_fulfilled", "fulfilled")],
            "hire_ended": [("item_returned", "item_returned")],
            "item_returned": [("order_fulfilled", "fulfilled")],
        }

        transitions = VALID_TRANSITIONS.get(order.status, [])
        allowed_matches = [t for t in transitions if t[0] == event]
        if not allowed_matches:
            return Response(
                {"error": f"Invalid status transition from current status '{order.status}' via event '{event}'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        next_status = allowed_matches[0][1]

        with transaction.atomic():
            order.status = next_status
            order.save(update_fields=['status'])

            # Log order activity
            OrderActivity.objects.create(
                order=order,
                event_type=event,
                message=note or f"Order advanced to {next_status.replace('_', ' ')}."
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
        return QuoteRequest.objects.filter(buyer=self.request.user).order_by("-created_at")


class SellerReceivedQuotesView(generics.ListAPIView):
    """
    Returns all QuoteRequest objects where the associated listing belongs to request.user's store, paginated, ordered by most recent first.
    """
    serializer_class = QuoteRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return QuoteRequest.objects.filter(
            Q(store__user=self.request.user) | Q(listing__store__user=self.request.user)
        ).distinct().order_by("-created_at")


class OrderInvoicePDFView(APIView):
    """
    Generates and returns a beautifully-styled PDF invoice for a specific order.
    Access restricted to buyer, seller, or admin/staff.
    """
    permission_classes = [permissions.IsAuthenticated]

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
        txn_data = [
            [
                Paragraph("<b>Transaction Type:</b>", header_style),
                Paragraph("<b>Order Status:</b>", header_style),
                Paragraph("<b>Payment Currency:</b>", header_style),
            ],
            [
                Paragraph(order.get_order_type_display(), body_style),
                Paragraph(order.get_status_display(), body_style),
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

        # 5. Rental Period details (if Hire or Lease)
        if order.order_type in [Order.OrderType.HIRE, Order.OrderType.LEASE] and order.rental_start_date:
            rental_data = [
                [
                    Paragraph("<b>Rental Start Date:</b>", header_style),
                    Paragraph("<b>Rental End Date:</b>", header_style),
                    Paragraph("<b>Total Rental Days:</b>", header_style),
                ],
                [
                    Paragraph(order.rental_start_date.strftime('%Y-%m-%d'), body_style),
                    Paragraph(order.rental_end_date.strftime('%Y-%m-%d') if order.rental_end_date else 'N/A', body_style),
                    Paragraph(str(order.rental_days_total) if order.rental_days_total else 'N/A', body_style),
                ]
            ]
            rental_table = Table(rental_data, colWidths=[2.33*inch, 2.33*inch, 2.34*inch])
            rental_table.setStyle(TableStyle([
                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                ('TOPPADDING', (0,0), (-1,-1), 4),
                ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#EEEEEE')),
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F9F9F9')),
            ]))
            story.append(rental_table)
            story.append(Spacer(1, 15))

        # 6. Itemized Marketplace Table
        item_table_data = [
            [
                Paragraph("Item Description / Listing", table_header_style),
                Paragraph("Transaction", table_header_style),
                Paragraph("Amount", table_header_style)
            ],
            [
                Paragraph(order.listing.title if order.listing else "Marketplace Item / Order Transaction", body_style),
                Paragraph(order.get_order_type_display(), body_style),
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
