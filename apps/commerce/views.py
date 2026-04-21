import uuid
import hmac
import hashlib
import requests

from decimal import Decimal
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.utils.dateparse import parse_date
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample
from rest_framework import generics, permissions, status
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


from .filters import OrderFilter, QuoteRequestFilter
from .models import Cart, CartItem, Order, OrderActivity, Payment, QuoteRequest
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
    QuoteRequestVendorUpdateSerializer
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
                    "duration_bucket": "",
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
                    "duration_bucket": "50_100_days",
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

        # Use quoted price if available, fallback to listing price
        quoted_price = request.data.get('quoted_price') or quote.listing.price

        CartItem.objects.update_or_create(
            cart=cart,
            listing=quote.listing,
            purchase_type=quote.purchase_type,
            defaults={
                'quantity': quote.quantity,
                'unit_price': quoted_price,
                'store': quote.store,
                'duration_days': None,
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
    post=extend_schema(summary="Extend order rental period"),
    examples=[
        OpenApiExample(
            "Extend order",
            value={
                "new_end_date": "2026-04-20T10:00:00Z"
            }
        )
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

        new_end_date = request.data.get('new_end_date')
        if not new_end_date:
            return Response({'error': 'new_end_date is required'}, status=400)

        from django.utils.dateparse import parse_date
        parsed = parse_date(new_end_date)
        if not parsed:
            return Response({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=400)

        if order.rental_end_date and parsed <= order.rental_end_date:
            return Response({'error': 'New end date must be after current end date'}, status=400)

        order.rental_end_date = parsed
        order.save(update_fields=['rental_end_date'])

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

            OrderActivity.objects.create(
                order=order,
                event_type=OrderActivity.EventType.ORDER_PLACED,
                message="Order placed successfully."
            )

            notify_order_placed(order)

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

            return Response({
                'status': 'success',
                'message': 'Payment verified successfully.',
                'order_id': payment.order_id,
            })

        payment.status = Payment.Status.FAILED
        payment.save(update_fields=['status'])
        return Response(
            {'status': 'failed', 'message': 'Payment not successful.'},
            status=status.HTTP_400_BAD_REQUEST
        )


