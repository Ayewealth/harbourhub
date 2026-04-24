from decimal import Decimal
from django.db.models import Q, Count, Avg, F
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import timedelta
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, permissions, status, filters
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_panel.permissions import IsAdminOrSuperAdmin
from .models import SupportTicket
from .serializers import (
    SupportTicketSerializer,
    SupportTicketCreateSerializer,
    MarkResolvedSerializer,
    SupportTicketSummarySerializer,
)


class SupportTicketListCreateView(generics.ListCreateAPIView):
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter
    ]
    filterset_fields = ['ticket_type', 'priority', 'status', 'raised_by_role']
    search_fields = ['subject', 'description', 'order__order_number']
    ordering_fields = ['created_at', 'priority', 'status']
    ordering = ['-created_at']

    def get_permissions(self):
        if self.request.method == 'POST':
            return [permissions.IsAuthenticated()]
        return [IsAdminOrSuperAdmin()]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return SupportTicketCreateSerializer
        return SupportTicketSerializer

    def get_queryset(self):
        user = self.request.user
        qs = SupportTicket.objects.select_related(
            'raised_by', 'order', 'listing', 'assigned_to'
        )
        # Non-admins see only their own tickets
        if not getattr(user, 'is_staff', False):
            return qs.filter(raised_by=user)
        return qs


class SupportTicketDetailView(generics.RetrieveAPIView):
    serializer_class = SupportTicketSerializer
    permission_classes = [IsAdminOrSuperAdmin]

    def get_queryset(self):
        return SupportTicket.objects.select_related(
            'raised_by', 'order', 'listing', 'assigned_to'
        )


class MarkTicketResolvedView(APIView):
    permission_classes = [IsAdminOrSuperAdmin]

    def post(self, request, pk):
        ticket = get_object_or_404(SupportTicket, pk=pk)

        if ticket.status == SupportTicket.Status.RESOLVED:
            return Response(
                {'error': 'Ticket is already resolved.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = MarkResolvedSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ticket.mark_as_resolved(
            admin_user=request.user,
            notes=serializer.validated_data.get('resolution_notes', '')
        )

        # Log action
        from apps.admin_panel.models import AdminActionLog
        AdminActionLog.log_action(
            admin_user=request.user,
            action_type='ticket_resolved',
            description=f"Resolved ticket #{ticket.pk}: {ticket.subject}",
        )

        return Response({'message': 'Ticket marked as resolved.'})


class SupportTicketSummaryView(APIView):
    permission_classes = [IsAdminOrSuperAdmin]

    def get(self, request):
        now = timezone.now()
        today_start = now.replace(
            hour=0, minute=0, second=0, microsecond=0)
        this_month = now.replace(day=1, hour=0, minute=0, second=0)
        last_month_start = (this_month - timedelta(days=1)).replace(day=1)

        qs = SupportTicket.objects.all()

        open_tickets = qs.filter(
            status__in=[
                SupportTicket.Status.OPEN,
                SupportTicket.Status.IN_PROGRESS
            ]
        ).count()

        from apps.commerce.models import Dispute
        
        active_disputes = Dispute.objects.filter(
            status__in=[
                Dispute.Status.OPEN,
                Dispute.Status.UNDER_REVIEW
            ]
        ).count()

        resolved_today = qs.filter(
            status=SupportTicket.Status.RESOLVED,
            resolved_at__gte=today_start
        ).count()

        # Avg resolution time in hours
        resolved = qs.filter(
            status=SupportTicket.Status.RESOLVED,
            resolved_at__isnull=False
        )
        avg_hours = 0.0
        if resolved.exists():
            total_hours = sum(
                (t.resolved_at - t.created_at).total_seconds() / 3600
                for t in resolved
            )
            avg_hours = round(total_hours / resolved.count(), 1)

        # % change vs last month
        def pct(current, previous):
            if previous == 0:
                return 100.0 if current > 0 else 0.0
            return round((current - previous) / previous * 100, 1)

        open_this = qs.filter(
            created_at__gte=this_month,
            status__in=[
                SupportTicket.Status.OPEN,
                SupportTicket.Status.IN_PROGRESS
            ]
        ).count()
        open_last = qs.filter(
            created_at__gte=last_month_start,
            created_at__lt=this_month,
            status__in=[
                SupportTicket.Status.OPEN,
                SupportTicket.Status.IN_PROGRESS
            ]
        ).count()

        disputes_this = Dispute.objects.filter(
            created_at__gte=this_month
        ).count()
        disputes_last = Dispute.objects.filter(
            created_at__gte=last_month_start,
            created_at__lt=this_month
        ).count()

        return Response({
            'open_tickets': open_tickets,
            'active_disputes': active_disputes,
            'resolved_today': resolved_today,
            'avg_resolution_time_hours': avg_hours,
            'open_change_percent': pct(open_this, open_last),
            'disputes_change_percent': pct(disputes_this, disputes_last),
        })
