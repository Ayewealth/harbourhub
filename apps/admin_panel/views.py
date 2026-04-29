from datetime import timedelta, timezone
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
            store.is_verified = True
            # store.is_published = True
            store.save(update_fields=['is_verified'])

            # Approve verification request
            vr = VerificationRequest.objects.filter(
                user=store.user,
                status='pending'
            ).first()
            if vr:
                vr.approve(admin_user=request.user, notes=notes)

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
            store.save(update_fields=['is_verified',])

            vr = VerificationRequest.objects.filter(
                user=store.user,
                status='pending'
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
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['status', 'gateway']
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
        from apps.commerce.models import Payment
        from django.db.models import Sum

        response = super().list(request, *args, **kwargs)

        now = timezone.now()
        this_month = now.replace(day=1, hour=0, minute=0, second=0)
        last_month = (this_month - timedelta(days=1)).replace(day=1)

        qs = Payment.objects.filter(status='success')

        def pct(cur, prev):
            if prev == 0:
                return 100.0 if cur > 0 else 0.0
            return round((cur - prev) / prev * 100, 1)

        total_vol = qs.aggregate(
            t=Sum('amount'))['t'] or 0
        platform_rev = qs.aggregate(
            t=Sum('order__escrow_fee'))['t'] or 0

        from apps.financials.models import Payout
        vendor_payouts = Payout.objects.filter(
            status='paid'
        ).aggregate(t=Sum('amount'))['t'] or 0
        pending_payouts = Payout.objects.filter(
            status__in=['requested', 'processing']
        ).aggregate(t=Sum('amount'))['t'] or 0

        this_vol = qs.filter(
            created_at__gte=this_month
        ).aggregate(t=Sum('amount'))['t'] or 0
        last_vol = qs.filter(
            created_at__gte=last_month,
            created_at__lt=this_month
        ).aggregate(t=Sum('amount'))['t'] or 0

        response.data['summary'] = {
            'total_transaction_volume': total_vol,
            'platform_revenue': platform_rev,
            'vendor_payouts': vendor_payouts,
            'pending_payouts': pending_payouts,
            'volume_change_percent': pct(this_vol, last_vol),
        }
        return response


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
    filterset_fields = ['status']
    search_fields = ['order_number', 'buyer__full_name', 'buyer__email']
    ordering_fields = ['created_at', 'total_amount']
    ordering = ['-created_at']

    def get_queryset(self):
        from apps.commerce.models import Order
        return Order.objects.select_related('buyer', 'listing').all()
