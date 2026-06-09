from datetime import timedelta
from django.utils import timezone
from rest_framework import viewsets, permissions, filters, status
from rest_framework import generics
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.decorators import action
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.permissions import IsAdminUser
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.views import APIView

from apps.notifications.utils import notify_verification_approved, notify_verification_rejected

from .models import ReportedContent, AdminActionLog, PlatformConfig
from .serializers import (
    ReportedContentSerializer,
    ReportedContentCreateSerializer,
    AdminActionLogSerializer,
    AdminOrderListSerializer
)
from .permissions import IsAdminOrSuperAdmin
from .auth import has_admin_module_permission, HasAdminModulePermission
from .tasks import send_verification_decision_email

from apps.accounts.models import VerificationRequest
from apps.accounts.serializers import VerificationRequestSerializer


@extend_schema_view(
    list=extend_schema(
        summary="List all reported content (admin only)",
        description="Retrieve all reported content for review and moderation."
    ),
    create=extend_schema(
        summary="Report content",
        description="Users can report listings, inquiries, or other users."
    ),
)
class ReportedContentViewSet(viewsets.ModelViewSet):
    """Content reporting system for users to report inappropriate content."""

    queryset = ReportedContent.objects.all().select_related(
        "reported_by", "reviewed_by"
    ).order_by("-created_at")
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["status", "reason", "content_type"]
    search_fields = ["description", "reported_by__email"]
    http_method_names = ['get', 'post']

    def get_serializer_class(self):
        if self.action == "create":
            return ReportedContentCreateSerializer
        return ReportedContentSerializer

    def get_permissions(self):
        """Only admins can view/manage; all authenticated users can create."""
        if self.action == "create":
            return [permissions.IsAuthenticated()]
        return [IsAdminUser()]

    def get_queryset(self):
        """Admins see all; users only create (no listing)."""
        if self.action == "create":
            return ReportedContent.objects.none()
        return super().get_queryset()

    def perform_create(self, serializer):
        """Attach current user as reporter and optionally trigger async task."""
        report = serializer.save(reported_by=self.request.user)

        AdminActionLog.log_action(
            admin_user=self.request.user,
            action_type=AdminActionLog.ActionType.REPORT_SUBMITTED,
            description=f"User reported {report.content_type} #{report.object_id}",
            extra_data={"reason": report.reason}
        )

        try:
            from .tasks import notify_admins_of_new_report
            notify_admins_of_new_report.delay(report.id)
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Admin moderation actions
    # -------------------------------------------------------------------------

    @extend_schema(
        summary="Resolve reported content",
        description="Mark reported content as resolved with optional admin notes."
    )
    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def resolve(self, request, pk=None):
        """Resolve a reported content entry."""
        report = self.get_object()
        admin_notes = request.data.get("admin_notes", "")
        action_taken = request.data.get("action_taken", "")

        report.status = ReportedContent.Status.RESOLVED
        report.mark_as_reviewed(request.user, admin_notes)

        AdminActionLog.log_action(
            admin_user=request.user,
            action_type=AdminActionLog.ActionType.CONTENT_RESOLVED,
            description=f"Resolved content report: {report.get_reason_display()}",
            extra_data={"action_taken": action_taken, "notes": admin_notes},
        )

        return Response(
            {"message": "Content report resolved successfully"},
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="Dismiss reported content",
        description="Dismiss the reported content as invalid."
    )
    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def dismiss(self, request, pk=None):
        """Dismiss a report as invalid or spam."""
        report = self.get_object()
        admin_notes = request.data.get(
            "admin_notes", "Report dismissed as invalid."
        )

        report.status = ReportedContent.Status.DISMISSED
        report.mark_as_reviewed(request.user, admin_notes)

        AdminActionLog.log_action(
            admin_user=request.user,
            action_type=AdminActionLog.ActionType.CONTENT_DISMISSED,
            description=f"Dismissed content report: {report.get_reason_display()}",
            extra_data={"notes": admin_notes},
        )

        return Response(
            {"message": "Content report dismissed successfully"},
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    list=extend_schema(summary="List verification requests",
                       description="Admins can list and filter verification requests."),
    retrieve=extend_schema(summary="Retrieve verification request detail"),
)
class VerificationAdminViewSet(viewsets.ModelViewSet):
    """Admin moderation for verification requests."""

    queryset = VerificationRequest.objects.select_related(
        "user", "reviewed_by").all()
    serializer_class = VerificationRequestSerializer
    permission_classes = [IsAdminOrSuperAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["status"]
    search_fields = ["user__email", "company_name"]

    @extend_schema(
        summary="Approve verification request",
        description="Admin approves a verification request and marks the user as verified.",
    )
    @action(detail=True, methods=["post"], url_path="approve")
    def approve_request(self, request, pk=None):
        verification = self.get_object()
        if verification.status != VerificationRequest.Status.PENDING:
            return Response({"error": "Only pending requests can be approved."},
                            status=status.HTTP_400_BAD_REQUEST)

        notes = request.data.get("admin_notes", "")
        verification.approve(admin_user=request.user, notes=notes)
        send_verification_decision_email.delay(verification.id)

        # Log admin action
        AdminActionLog.log_action(
            admin_user=request.user,
            action_type=AdminActionLog.ActionType.VERIFICATION_APPROVED,
            description=f"Approved verification for {verification.user.email}",
            extra_data={"notes": notes},
        )

        notify_verification_approved(verification.user)

        return Response(
            {"message": "Verification approved successfully."},
            status=status.HTTP_200_OK
        )

    @extend_schema(
        summary="Reject verification request",
        description="Admin rejects a verification request with notes.",
    )
    @action(detail=True, methods=["post"], url_path="reject")
    def reject_request(self, request, pk=None):
        verification = self.get_object()
        if verification.status != VerificationRequest.Status.PENDING:
            return Response({"error": "Only pending requests can be rejected."},
                            status=status.HTTP_400_BAD_REQUEST)

        notes = request.data.get(
            "admin_notes", "Verification request rejected.")
        verification.reject(admin_user=request.user, notes=notes)
        send_verification_decision_email.delay(verification.id)

        # Log admin action
        AdminActionLog.log_action(
            admin_user=request.user,
            action_type=AdminActionLog.ActionType.VERIFICATION_REJECTED,
            description=f"Rejected verification for {verification.user.email}",
            extra_data={"notes": notes},
        )

        notify_verification_rejected(
            verification.user, notes=notes)

        return Response(
            {"message": "Verification rejected successfully."},
            status=status.HTTP_200_OK
        )


class AdminVendorListView(generics.ListAPIView):
    """Admin view of all vendors with metrics."""
    permission_classes = [IsAdminOrSuperAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = ['user__email', 'name', 'user__company']

    def get_queryset(self):
        from apps.store.models import Store
        return Store.objects.select_related(
            'user'
        ).prefetch_related('categories').order_by('-created_at')

    def get_serializer_class(self):
        from apps.store.serializers import StoreListSerializer
        return StoreListSerializer

    def list(self, request, *args, **kwargs):
        from apps.store.models import Store
        from apps.accounts.models import VerificationRequest

        qs = self.get_queryset()
        page = self.paginate_queryset(
            self.filter_queryset(qs))

        from apps.store.serializers import StoreListSerializer
        serializer = StoreListSerializer(
            page, many=True, context={'request': request})

        response = self.get_paginated_response(serializer.data)

        # Add summary metrics
        now = timezone.now()
        this_month = now.replace(day=1, hour=0, minute=0, second=0)
        last_month = (this_month - timedelta(days=1)).replace(day=1)

        def pct(cur, prev):
            if prev == 0:
                return 100.0 if cur > 0 else 0.0
            return round((cur - prev) / prev * 100, 1)

        total = Store.objects.count()
        pending = VerificationRequest.objects.filter(
            status='pending').count()
        approved = Store.objects.filter(
            is_verified=True).count()
        rejected = VerificationRequest.objects.filter(
            status='rejected').count()

        total_last = Store.objects.filter(
            created_at__lt=this_month).count()
        pending_last = VerificationRequest.objects.filter(
            status='pending',
            created_at__gte=last_month,
            created_at__lt=this_month
        ).count()

        response.data['summary'] = {
            'total_vendors': total,
            'pending_approval': pending,
            'approved_vendors': approved,
            'rejected_suspended': rejected,
            'total_change_percent': pct(total, total_last),
            'pending_change_percent': pct(pending, pending_last),
        }
        return response


class AdminVendorActionView(APIView):
    """Approve, reject, or suspend a vendor."""
    permission_classes = [IsAdminOrSuperAdmin]

    def post(self, request, pk, action):
        from apps.store.models import Store
        from apps.accounts.models import VerificationRequest

        store = get_object_or_404(Store, pk=pk)
        reason = request.data.get('reason', '')
        notes = request.data.get('notes', '')
        duration = request.data.get('duration', 'indefinite')

        if action == 'approve':
            vr = VerificationRequest.objects.filter(
                user=store.user
            ).first()

            if vr:
                vr.approve(admin_user=request.user, notes=notes)
            else:
                store.is_verified = True
                store.save(update_fields=['is_verified'])
                store.user.is_verified = True
                store.user.save(update_fields=['is_verified'])

            from apps.notifications.utils import notify_verification_approved
            notify_verification_approved(store.user)

            AdminActionLog.log_action(
                admin_user=request.user,
                action_type=AdminActionLog.ActionType.USER_VERIFIED,
                description=f"Approved vendor: {store.name}",
            )
            return Response({'message': 'Vendor approved successfully.'})

        elif action == 'reject':
            store.is_verified = False
            store.save(update_fields=['is_verified'])
            store.user.is_verified = False
            store.user.save(update_fields=['is_verified'])

            vr = VerificationRequest.objects.filter(
                user=store.user
            ).first()
            if vr:
                vr.reject(admin_user=request.user, notes=reason)

            from apps.notifications.utils import notify_verification_rejected
            notify_verification_rejected(store.user, notes=reason)

            AdminActionLog.log_action(
                admin_user=request.user,
                action_type=AdminActionLog.ActionType.USER_REJECTED,
                description=f"Rejected vendor: {store.name}. Reason: {reason}",
            )
            return Response({'message': 'Vendor rejected.'})

        elif action == 'suspend':
            store.is_active = False
            store.save(update_fields=['is_active'])

            from apps.notifications.utils import create_notification
            create_notification(
                recipient=store.user,
                notification_type='store_verified',
                title='Store Suspended',
                message=(
                    f"Your store has been suspended. "
                    f"Reason: {reason}. Duration: {duration}."
                ),
                priority='high',
            )

            AdminActionLog.log_action(
                admin_user=request.user,
                action_type=AdminActionLog.ActionType.USER_BANNED,
                description=(
                    f"Suspended vendor: {store.name}. "
                    f"Reason: {reason}. Duration: {duration}."
                ),
            )
            return Response({'message': 'Vendor suspended.'})

        return Response(
            {'error': 'Invalid action.'},
            status=status.HTTP_400_BAD_REQUEST
        )


class AdminListingListView(generics.ListAPIView):
    """Admin view of all listings."""
    permission_classes = [IsAdminOrSuperAdmin]
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter
    ]
    search_fields = ['title', 'user__email', 'manufacturer']
    ordering_fields = ['created_at', 'updated_at', 'status']
    ordering = ['-created_at']

    def get_queryset(self):
        from apps.listings.models import Listing
        return Listing.objects.select_related(
            'user', 'category', 'store'
        ).prefetch_related('images')

    def get_serializer_class(self):
        from apps.listings.serializers import ListingListSerializer
        return ListingListSerializer


class AdminListingActionView(APIView):
    """Approve, reject, or deactivate a listing."""
    permission_classes = [IsAdminOrSuperAdmin]

    def post(self, request, pk, action):
        from apps.listings.models import Listing
        from apps.notifications.utils import create_notification

        listing = get_object_or_404(Listing, pk=pk)
        reason = request.data.get('reason', '')
        notes = request.data.get('notes', '')

        if action == 'approve':
            listing.status = Listing.Status.PUBLISHED
            listing.save(update_fields=['status', 'published_at'])

            create_notification(
                recipient=listing.user,
                notification_type='listing_approved',
                title='Listing Approved',
                message=f"Your listing '{listing.title}' has been approved.",
                priority='high',
                action_url=f"/listings/{listing.id}",
                action_label="View Listing",
            )

            AdminActionLog.log_action(
                admin_user=request.user,
                action_type=AdminActionLog.ActionType.LISTING_PUBLISHED,
                description=f"Approved listing: {listing.title}",
            )
            return Response({'message': 'Listing approved successfully.'})

        elif action == 'reject':
            listing.status = Listing.Status.ARCHIVED
            listing.save(update_fields=['status'])

            create_notification(
                recipient=listing.user,
                notification_type='listing_rejected',
                title='Listing Rejected',
                message=(
                    f"Your listing '{listing.title}' was rejected. "
                    f"Reason: {reason}"
                ),
                priority='high',
            )

            AdminActionLog.log_action(
                admin_user=request.user,
                action_type=AdminActionLog.ActionType.LISTING_REMOVED,
                description=(
                    f"Rejected listing: {listing.title}. Reason: {reason}"
                ),
            )
            return Response({'message': 'Listing rejected.'})

        elif action == 'deactivate':
            listing.status = Listing.Status.SUSPENDED
            listing.save(update_fields=['status'])

            create_notification(
                recipient=listing.user,
                notification_type='listing_rejected',
                title='Listing Deactivated',
                message=(
                    f"Your listing '{listing.title}' has been deactivated. "
                    f"Reason: {reason}. Notes: {notes}"
                ),
                priority='high',
            )

            AdminActionLog.log_action(
                admin_user=request.user,
                action_type=AdminActionLog.ActionType.LISTING_ARCHIVED,
                description=(
                    f"Deactivated listing: {listing.title}. Reason: {reason}"
                ),
            )
            return Response({'message': 'Listing deactivated.'})

        return Response(
            {'error': 'Invalid action.'},
            status=status.HTTP_400_BAD_REQUEST
        )


class AdminPaymentListView(generics.ListAPIView):
    """Admin view of all payments/transactions."""
    permission_classes = [IsAdminOrSuperAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    from apps.commerce.filters import PaymentFilter
    filterset_class = PaymentFilter
    search_fields = ['reference', 'order__order_number', 'buyer__email']

    def get_queryset(self):
        from apps.commerce.models import Payment
        return Payment.objects.select_related(
            'order', 'buyer',
            'order__seller', 'order__listing'
        ).order_by('-created_at')

    def get_serializer_class(self):
        from apps.commerce.serializers import PaymentSerializer
        return PaymentSerializer
    def list(self, request, *args, **kwargs):
        # The summary stats are now in a dedicated /stats/ endpoint.
        return super().list(request, *args, **kwargs)


class AdminPaymentStatsView(APIView):
    """
    Dedicated stats for Payment module cards.
    Supports ?date_from= and ?date_to= filtering.
    """
    permission_classes = [IsAdminOrSuperAdmin]

    @extend_schema(
        summary="Payment statistics for dashboard cards",
        description="Returns Total Volume, Platform Revenue, Vendor Payouts, and Pending Payouts.",
    )
    def get(self, request):
        from apps.commerce.models import Payment
        from apps.financials.models import Payout
        from django.db.models import Sum
        from django.utils.dateparse import parse_date

        now = timezone.now()
        raw_from = request.query_params.get("date_from")
        raw_to = request.query_params.get("date_to")

        if raw_from and raw_to:
            date_from = parse_date(raw_from)
            date_to = parse_date(raw_to)
            period_start = timezone.make_aware(timezone.datetime.combine(date_from, timezone.datetime.min.time()))
            period_end = timezone.make_aware(timezone.datetime.combine(date_to, timezone.datetime.max.time()))
        else:
            period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            period_end = now

        period_length = period_end - period_start
        prev_end = period_start
        prev_start = period_start - period_length

        def get_metrics(start, end):
            payments = Payment.objects.filter(status='success', created_at__gte=start, created_at__lte=end)
            vol = payments.aggregate(t=Sum('amount'))['t'] or 0
            rev = payments.aggregate(t=Sum('order__escrow_fee'))['t'] or 0
            
            payouts_paid = Payout.objects.filter(status='paid', created_at__gte=start, created_at__lte=end)
            paid_payouts = payouts_paid.aggregate(t=Sum('amount'))['t'] or 0
            
            payouts_pending = Payout.objects.filter(status__in=['requested', 'processing'], created_at__gte=start, created_at__lte=end)
            pend_payouts = payouts_pending.aggregate(t=Sum('amount'))['t'] or 0
            
            return {
                "total_volume": float(vol),
                "platform_revenue": float(rev),
                "vendor_payouts": float(paid_payouts),
                "pending_payouts": float(pend_payouts)
            }

        cur = get_metrics(period_start, period_end)
        prev = get_metrics(prev_start, prev_end)

        def pct(c, p):
            if p == 0: return 100.0 if c > 0 else 0.0
            return round((c - p) / p * 100, 1)

        return Response({
            "total_volume": {"value": cur["total_volume"], "change_percent": pct(cur["total_volume"], prev["total_volume"])},
            "platform_revenue": {"value": cur["platform_revenue"], "change_percent": pct(cur["platform_revenue"], prev["platform_revenue"])},
            "vendor_payouts": {"value": cur["vendor_payouts"], "change_percent": pct(cur["vendor_payouts"], prev["vendor_payouts"])},
            "pending_payouts": {"value": cur["pending_payouts"], "change_percent": pct(cur["pending_payouts"], prev["pending_payouts"])}
        })


class AdminReportStatsView(APIView):
    """
    Dedicated stats for Analytics Reports tab.
    """
    permission_classes = [IsAdminOrSuperAdmin]

    @extend_schema(
        summary="Analytics reports metric cards",
        description="Returns Total Revenue, Active Disputes, and New Inquiries.",
    )
    def get(self, request):
        from apps.commerce.models import Payment, Dispute, QuoteRequest
        from django.db.models import Sum
        from django.utils.dateparse import parse_date

        now = timezone.now()
        raw_from = request.query_params.get("date_from")
        raw_to = request.query_params.get("date_to")

        if raw_from and raw_to:
            date_from = parse_date(raw_from)
            date_to = parse_date(raw_to)
            period_start = timezone.make_aware(timezone.datetime.combine(date_from, timezone.datetime.min.time()))
            period_end = timezone.make_aware(timezone.datetime.combine(date_to, timezone.datetime.max.time()))
        else:
            period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            period_end = now

        period_length = period_end - period_start
        prev_end = period_start
        prev_start = period_start - period_length

        def get_metrics(start, end):
            rev = Payment.objects.filter(
                status='success', created_at__gte=start, created_at__lte=end
            ).aggregate(t=Sum('order__escrow_fee'))['t'] or 0
            
            disputes = Dispute.objects.filter(
                status__in=['open', 'under_review'], created_at__gte=start, created_at__lte=end
            ).count()
            
            inquiries = QuoteRequest.objects.filter(
                created_at__gte=start, created_at__lte=end
            ).count()
            
            return {
                "total_revenue": float(rev),
                "active_disputes": disputes,
                "new_inquiries": inquiries
            }

        cur = get_metrics(period_start, period_end)
        prev = get_metrics(prev_start, prev_end)

        def pct(c, p):
            if p == 0: return 100.0 if c > 0 else 0.0
            return round((c - p) / p * 100, 1)

        return Response({
            "total_revenue": {"value": cur["total_revenue"], "change_percent": pct(cur["total_revenue"], prev["total_revenue"])},
            "active_disputes": {"value": cur["active_disputes"], "change_percent": pct(cur["active_disputes"], prev["active_disputes"])},
            "new_inquiries": {"value": cur["new_inquiries"], "change_percent": pct(cur["new_inquiries"], prev["new_inquiries"])}
        })


class AdminMarkPayoutPaidView(APIView):
    """Admin manually marks a payout as paid."""
    permission_classes = [IsAdminOrSuperAdmin]

    def post(self, request, pk):
        from apps.financials.models import Payout, VendorEarning

        payout = get_object_or_404(Payout, pk=pk)

        if payout.status == Payout.Status.PAID:
            return Response(
                {'error': 'Payout already marked as paid.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        payout.status = Payout.Status.PAID
        payout.processed_at = timezone.now()
        payout.save(update_fields=['status', 'processed_at'])

        # Mark earnings as paid out
        VendorEarning.objects.filter(
            vendor=payout.vendor,
            status=VendorEarning.Status.AVAILABLE
        ).update(status=VendorEarning.Status.PAID_OUT)

        from apps.notifications.utils import notify_payout_processed
        notify_payout_processed(payout)

        AdminActionLog.log_action(
            admin_user=request.user,
            action_type='payout_marked_paid',
            description=f"Manually marked payout #{payout.pk} as paid.",
        )

        return Response({'message': 'Payout marked as paid.'})


class AdminActivityViewSet(viewsets.ReadOnlyModelViewSet):
    """Admin view of platform activity logs."""
    queryset = AdminActionLog.objects.select_related('admin_user').all()
    serializer_class = AdminActionLogSerializer
    permission_classes = [IsAdminOrSuperAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['action_type', 'admin_user']
    search_fields = ['description', 'admin_user__email']
    ordering = ['-timestamp']


class AdminOrderViewSet(viewsets.ReadOnlyModelViewSet):
    """Admin view of all platform orders."""
    serializer_class = AdminOrderListSerializer
    permission_classes = [IsAdminOrSuperAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    from apps.commerce.filters import OrderFilter
    filterset_class = OrderFilter
    search_fields = ['order_number', 'buyer__full_name', 'buyer__email']
    ordering_fields = ['created_at', 'total_amount']
    ordering = ['-created_at']

    def get_queryset(self):
        from apps.commerce.models import Order
        return Order.objects.select_related('buyer', 'listing').all()

    @extend_schema(
        summary="Order statistics for dashboard cards",
        description=(
            "Returns Total Orders, Active Orders, Pending Quote Requests, and "
            "Completed Transactions — each with a percentage change vs the previous "
            "equivalent period. Filter using `date_from` and `date_to` (YYYY-MM-DD). "
            "Defaults to the current calendar month vs the previous month."
        ),
        parameters=[
            {
                "name": "date_from",
                "in": "query",
                "required": False,
                "schema": {"type": "string", "format": "date"},
                "description": "Start of the period (YYYY-MM-DD)",
            },
            {
                "name": "date_to",
                "in": "query",
                "required": False,
                "schema": {"type": "string", "format": "date"},
                "description": "End of the period (YYYY-MM-DD)",
            },
        ],
    )
    @action(detail=False, methods=["get"], url_path="stats", url_name="stats")
    def stats(self, request):
        from apps.commerce.models import Order, QuoteRequest
        from django.utils.dateparse import parse_date

        now = timezone.now()

        # ── Resolve current period ──────────────────────────────────────────
        raw_from = request.query_params.get("date_from")
        raw_to   = request.query_params.get("date_to")

        if raw_from and raw_to:
            date_from = parse_date(raw_from)
            date_to   = parse_date(raw_to)
            if not date_from or not date_to:
                return Response(
                    {"error": "Invalid date format. Use YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            # Convert dates → aware datetimes (start of day / end of day)
            period_start = timezone.make_aware(
                timezone.datetime.combine(date_from, timezone.datetime.min.time())
            )
            period_end = timezone.make_aware(
                timezone.datetime.combine(date_to, timezone.datetime.max.time())
            )
        else:
            # Default: current calendar month
            period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            period_end   = now

        period_length = period_end - period_start

        # ── Resolve previous (comparison) period ───────────────────────────
        prev_end   = period_start
        prev_start = period_start - period_length

        # ── Helper: % change ───────────────────────────────────────────────
        def pct_change(current, previous):
            if previous == 0:
                return 100.0 if current > 0 else 0.0
            return round((current - previous) / previous * 100, 1)

        def card(label, current, previous):
            return {
                "label":          label,
                "value":          current,
                "change_percent": pct_change(current, previous),
                "increased":      current >= previous,
            }

        # ── Queries ────────────────────────────────────────────────────────
        orders     = Order.objects
        quotes     = QuoteRequest.objects

        # Total Orders
        total_cur  = orders.filter(created_at__gte=period_start, created_at__lte=period_end).count()
        total_prev = orders.filter(created_at__gte=prev_start,   created_at__lt=prev_end).count()

        # Active Orders  (paid or pending_payment — money is moving)
        active_statuses = [Order.Status.PAID, Order.Status.PENDING_PAYMENT]
        active_cur  = orders.filter(
            status__in=active_statuses,
            created_at__gte=period_start, created_at__lte=period_end
        ).count()
        active_prev = orders.filter(
            status__in=active_statuses,
            created_at__gte=prev_start, created_at__lt=prev_end
        ).count()

        # Pending Requests  (unresponded quote requests)
        pending_cur  = quotes.filter(
            status=QuoteRequest.Status.PENDING,
            created_at__gte=period_start, created_at__lte=period_end
        ).count()
        pending_prev = quotes.filter(
            status=QuoteRequest.Status.PENDING,
            created_at__gte=prev_start, created_at__lt=prev_end
        ).count()

        # Completed Transactions
        completed_cur  = orders.filter(
            status=Order.Status.FULFILLED,
            created_at__gte=period_start, created_at__lte=period_end
        ).count()
        completed_prev = orders.filter(
            status=Order.Status.FULFILLED,
            created_at__gte=prev_start, created_at__lt=prev_end
        ).count()

        return Response({
            "period": {
                "from": period_start.date().isoformat(),
                "to":   period_end.date().isoformat(),
            },
            "stats": [
                card("Total Orders",            total_cur,     total_prev),
                card("Active Orders",           active_cur,    active_prev),
                card("Pending Requests",        pending_cur,   pending_prev),
                card("Completed Transactions",  completed_cur, completed_prev),
            ],
        })


class AdminAnalyticsExportView(APIView):
    """
    Export analytics data to CSV/XLSX.
    """
    permission_classes = [IsAdminOrSuperAdmin]

    @extend_schema(
        summary="Export analytics data",
        description="Returns a CSV/XLSX file of platform analytics.",
    )
    def get(self, request):
        import csv
        from django.http import HttpResponse
        from django.utils.dateparse import parse_date

        raw_from = request.query_params.get("date_from")
        raw_to = request.query_params.get("date_to")
        
        # Simple CSV export placeholder
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="analytics_export_{raw_from or "all"}_to_{raw_to or "now"}.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Metric', 'Value', 'Period'])
        writer.writerow(['Total Revenue', '241000.00', f'{raw_from} to {raw_to}' if raw_from else 'Current Month'])
        writer.writerow(['Active Disputes', '14', 'N/A'])
        
        return response


class AdminGlobalSearchView(APIView):
    """
    Global search for orders, listings, and vendors.
    Used by the top search bar.
    """
    permission_classes = [IsAdminOrSuperAdmin]

    @extend_schema(
        summary="Global admin search",
        description="Search across listings, orders, and vendors.",
    )
    def get(self, request):
        query = request.query_params.get('q', '')
        if not query:
            return Response({'results': []})

        from apps.listings.models import Listing
        from apps.commerce.models import Order
        from apps.accounts.models import User

        listings = Listing.objects.filter(title__icontains=query)[:5]
        orders = Order.objects.filter(order_number__icontains=query)[:5]
        users = User.objects.filter(email__icontains=query)[:5]

        results = []
        for l in listings:
            results.append({'type': 'listing', 'id': l.id, 'title': l.title})
        for o in orders:
            results.append({'type': 'order', 'id': o.id, 'title': o.order_number})
        for u in users:
            results.append({'type': 'vendor', 'id': u.id, 'title': u.email})

        return Response({'results': results})


# ─── Admin Order Tracking ─────────────────────────────────────────────────────
from apps.commerce.serializers import AdminOrderTrackingSerializer

class AdminOrderTrackingView(generics.RetrieveAPIView):
    """
    Admin-only order tracking detail view with escrow and dispute highlights.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AdminOrderTrackingSerializer

    def get_object(self):
        pk_or_num = self.kwargs.get("pk_or_num")
        from apps.commerce.models import Order
        if str(pk_or_num).isdigit():
            order = get_object_or_404(Order, pk=pk_or_num)
        else:
            order = get_object_or_404(Order, order_number=pk_or_num)
        
        user = self.request.user
        is_admin = getattr(user, 'is_admin_user', False) or user.is_staff
        if not is_admin:
            from rest_framework import exceptions
            raise exceptions.PermissionDenied("You do not have permission to access the admin order tracking view.")
        return order


# ─── Admin Chat Monitoring Serializers & Views ─────────────────────────────────
from rest_framework import serializers

class AdminConversationListSerializer(serializers.ModelSerializer):
    buyer_name = serializers.CharField(source="buyer.full_name")
    buyer_email = serializers.CharField(source="buyer.email")
    seller_name = serializers.SerializerMethodField()
    seller_email = serializers.CharField(source="vendor.email")
    listing_title = serializers.CharField(source="listing.title", default="")
    last_message = serializers.CharField(source="last_message_preview", default="")

    class Meta:
        from apps.messaging.models import Conversation
        model = Conversation
        fields = (
            "id",
            "buyer_name",
            "buyer_email",
            "seller_name",
            "seller_email",
            "listing_title",
            "last_message",
            "last_message_at",
        )

    def get_seller_name(self, obj):
        if obj.store:
            return obj.store.name
        return obj.vendor.full_name or obj.vendor.username or obj.vendor.email


class AdminMessageSerializer(serializers.ModelSerializer):
    sender_role = serializers.CharField(source="sender.role")
    sender_name = serializers.CharField(source="sender.full_name")
    text = serializers.CharField(source="body")
    timestamp = serializers.DateTimeField(source="created_at")
    attachments = serializers.SerializerMethodField()

    class Meta:
        from apps.messaging.models import Message
        model = Message
        fields = (
            "id",
            "sender_role",
            "sender_name",
            "text",
            "timestamp",
            "attachments",
        )

    def get_attachments(self, obj):
        return []


class AdminConversationListView(generics.ListAPIView):
    """
    Returns a paginated list of all active buyer-seller chat threads across the platform.
    """
    permission_classes = [permissions.IsAuthenticated, HasAdminModulePermission]
    admin_module = "messages_monitoring"
    serializer_class = AdminConversationListSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = [
        'buyer__email', 'buyer__first_name', 'buyer__last_name',
        'vendor__email', 'vendor__first_name', 'vendor__last_name',
        'store__name',
    ]

    def get_queryset(self):
        from apps.messaging.models import Conversation
        return Conversation.objects.all().select_related("buyer", "vendor", "store", "listing")


class AdminConversationMessageHistoryView(generics.ListAPIView):
    """
    Returns the full paginated, chronologically ordered message history for a specific conversation.
    """
    permission_classes = [permissions.IsAuthenticated, HasAdminModulePermission]
    admin_module = "messages_monitoring"
    serializer_class = AdminMessageSerializer

    def get_queryset(self):
        from apps.messaging.models import Conversation, Message
        pk = self.kwargs.get("pk")
        conv = get_object_or_404(Conversation, pk=pk)
        return Message.objects.filter(conversation=conv).order_by("created_at")


# ─── Careers Module ───────────────────────────────────────────────────────────
from .serializers import JobListingSerializer

class PublicJobListingViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Public viewset to list active job openings and retrieve a single job opening.
    """
    permission_classes = [] # Public
    authentication_classes = []
    serializer_class = JobListingSerializer

    def get_queryset(self):
        from .models import JobListing
        return JobListing.objects.filter(is_active=True).order_by("-created_at")


class AdminJobListingViewSet(viewsets.ModelViewSet):
    """
    Admin management viewset for Job Listings.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = JobListingSerializer

    def get_queryset(self):
        from .models import JobListing
        return JobListing.objects.all().order_by("-created_at")

    def check_permissions(self, request):
        super().check_permissions(request)
        if not has_admin_module_permission(request.user, "careers", require_manage=True):
            self.permission_denied(
                request,
                message="You do not have permission to manage careers."
            )


# ─── Admin User Management ────────────────────────────────────────────────────

class AdminUserListView(generics.ListAPIView):
    """Admin view of all platform users (buyers, sellers, service providers)."""
    permission_classes = [IsAdminOrSuperAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = None  # set in __init__ to avoid circular imports
    search_fields = ['email', 'full_name', 'phone', 'company']
    ordering_fields = ['created_at', 'email', 'full_name', 'last_login']
    ordering = ['-created_at']

    def get_queryset(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        return User.objects.filter(
            role__in=['buyer', 'seller', 'service_provider']
        ).order_by('-created_at')

    def get_serializer_class(self):
        from apps.accounts.serializers import UserListSerializer
        return UserListSerializer

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.filterset_class is None:
            from .filters import AdminUserFilter
            self.filterset_class = AdminUserFilter


class AdminUserActionView(APIView):
    """Suspend or resume a platform user."""
    permission_classes = [IsAdminOrSuperAdmin]

    def post(self, request, pk, action):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = get_object_or_404(User, pk=pk)

        if user.role in ['admin', 'super_admin']:
            return Response(
                {'error': 'Cannot suspend or resume admin users.'},
                status=status.HTTP_403_FORBIDDEN
            )

        reason = request.data.get('reason', '')

        if action == 'suspend':
            user.is_active = False
            user.save(update_fields=['is_active'])

            AdminActionLog.log_action(
                admin_user=request.user,
                action_type=AdminActionLog.ActionType.USER_BANNED,
                description=f"Suspended user: {user.email}. Reason: {reason}",
            )
            return Response({'message': 'User suspended successfully.'})

        elif action == 'resume':
            user.is_active = True
            user.save(update_fields=['is_active'])

            AdminActionLog.log_action(
                admin_user=request.user,
                action_type=AdminActionLog.ActionType.USER_UNBANNED,
                description=f"Resumed user: {user.email}.",
            )
            return Response({'message': 'User resumed successfully.'})

        return Response(
            {'error': 'Invalid action.'},
            status=status.HTTP_400_BAD_REQUEST
        )
