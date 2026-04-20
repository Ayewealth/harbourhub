from django.db.models import Avg, Count, Q
from django.utils.dateparse import parse_date
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_panel.auth import has_admin_module_permission
from apps.admin_panel.constants import AdminModule

from .filters import OrderFilter, QuoteRequestFilter
from .models import Order, QuoteRequest
from .serializers import (
    OrderCreateSerializer,
    OrderSerializer,
    QuoteRequestCreateSerializer,
    QuoteRequestSerializer,
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

        elif action == 'convert':
            if quote.status != QuoteRequest.Status.RESPONDED:
                return Response({'error': 'Only responded quotes can be converted'}, status=400)
            quote.status = QuoteRequest.Status.CONVERTED

        else:
            return Response({'error': 'Invalid action'}, status=400)

        quote.save(update_fields=['status'])
        return Response({'message': f'Quote {action}ed successfully'})


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
        return Response({'message': 'Order cancelled successfully'})


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
