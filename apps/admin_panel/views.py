from rest_framework import viewsets, permissions, filters, status
from rest_framework.response import Response
from rest_framework.decorators import action
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.permissions import IsAdminUser
from drf_spectacular.utils import extend_schema, extend_schema_view

from .models import ReportedContent, AdminActionLog
from .serializers import ReportedContentSerializer, ReportedContentCreateSerializer
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

        # Optional: send async admin notification (if Celery is active)
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
            action_type=AdminActionLog.ActionType.CONTENT_REVIEWED,
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
            action_type=AdminActionLog.ActionType.CONTENT_REVIEWED,
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
            action_type=AdminActionLog.ActionType.USER_VERIFIED,
            description=f"Approved verification for {verification.user.email}",
            extra_data={"notes": notes},
        )

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
            action_type=AdminActionLog.ActionType.USER_VERIFIED,
            description=f"Rejected verification for {verification.user.email}",
            extra_data={"notes": notes},
        )

        return Response(
            {"message": "Verification rejected successfully."},
            status=status.HTTP_200_OK
        )
