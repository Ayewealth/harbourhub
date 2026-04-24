from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import timedelta
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, permissions, status, filters
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_panel.permissions import IsAdminOrSuperAdmin
from .models import ComplianceDocument
from .serializers import (
    ComplianceDocumentSerializer,
    ComplianceDocumentCreateSerializer,
    VerifyDocumentSerializer,
)


class ComplianceDocumentListCreateView(generics.ListCreateAPIView):
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter
    ]
    filterset_fields = [
        'document_type', 'status', 'party_role', 'is_verified']
    search_fields = ['name', 'party__email', 'order__order_number']
    ordering_fields = ['created_at', 'end_date', 'status']
    ordering = ['-created_at']

    def get_permissions(self):
        if self.request.method == 'POST':
            return [permissions.IsAuthenticated()]
        return [IsAdminOrSuperAdmin()]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return ComplianceDocumentCreateSerializer
        return ComplianceDocumentSerializer

    def get_queryset(self):
        user = self.request.user
        qs = ComplianceDocument.objects.select_related(
            'party', 'order', 'listing', 'reviewed_by'
        )
        if not getattr(user, 'is_staff', False):
            return qs.filter(party=user)
        return qs


class ComplianceDocumentDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAdminOrSuperAdmin]
    serializer_class = ComplianceDocumentSerializer

    def get_queryset(self):
        return ComplianceDocument.objects.select_related(
            'party', 'order', 'listing', 'reviewed_by'
        )


class VerifyComplianceDocumentView(APIView):
    permission_classes = [IsAdminOrSuperAdmin]

    def post(self, request, pk):
        doc = get_object_or_404(ComplianceDocument, pk=pk)
        serializer = VerifyDocumentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        doc.is_verified = serializer.validated_data['is_verified']
        doc.admin_notes = serializer.validated_data.get('admin_notes', '')
        doc.reviewed_by = request.user
        doc.reviewed_at = timezone.now()
        if doc.is_verified:
            doc.verified_at = timezone.now()
            doc.status = ComplianceDocument.Status.ACTIVE
        else:
            doc.status = ComplianceDocument.Status.REJECTED
        doc.save()

        from apps.admin_panel.models import AdminActionLog
        AdminActionLog.log_action(
            admin_user=request.user,
            action_type='compliance_document_verified',
            description=(
                f"{'Verified' if doc.is_verified else 'Rejected'} "
                f"document: {doc.name}"
            ),
        )

        return Response({
            'message': (
                f"Document {'verified' if doc.is_verified else 'rejected'}."
            )
        })


class ComplianceSummaryView(APIView):
    permission_classes = [IsAdminOrSuperAdmin]

    def get(self, request):
        now = timezone.now()
        this_month = now.replace(day=1, hour=0, minute=0, second=0)
        last_month_start = (this_month - timedelta(days=1)).replace(day=1)
        expiry_warning_days = 10

        qs = ComplianceDocument.objects.all()

        active = qs.filter(status=ComplianceDocument.Status.ACTIVE).count()
        expiring = qs.filter(
            status=ComplianceDocument.Status.EXPIRING).count()
        expired = qs.filter(status=ComplianceDocument.Status.EXPIRED).count()
        missing = qs.filter(
            document_type=ComplianceDocument.DocumentType.CERTIFICATION,
            is_verified=False
        ).count()

        def pct(current, previous):
            if previous == 0:
                return 100.0 if current > 0 else 0.0
            return round((current - previous) / previous * 100, 1)

        active_this = qs.filter(
            status=ComplianceDocument.Status.ACTIVE,
            created_at__gte=this_month
        ).count()
        active_last = qs.filter(
            status=ComplianceDocument.Status.ACTIVE,
            created_at__gte=last_month_start,
            created_at__lt=this_month
        ).count()

        expiring_this = qs.filter(
            status=ComplianceDocument.Status.EXPIRING,
            created_at__gte=this_month
        ).count()
        expiring_last = qs.filter(
            status=ComplianceDocument.Status.EXPIRING,
            created_at__gte=last_month_start,
            created_at__lt=this_month
        ).count()

        return Response({
            'active_contracts': active,
            'expiring_soon': expiring,
            'expired': expired,
            'missing_certifications': missing,
            'active_change_percent': pct(active_this, active_last),
            'expiring_change_percent': pct(expiring_this, expiring_last),
        })
