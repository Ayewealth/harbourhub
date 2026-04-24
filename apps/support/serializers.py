from rest_framework import serializers
from .models import SupportTicket


class SupportTicketSerializer(serializers.ModelSerializer):
    raised_by_name = serializers.CharField(
        source='raised_by.get_full_name', read_only=True)
    raised_by_email = serializers.EmailField(
        source='raised_by.email', read_only=True)
    order_number = serializers.CharField(
        source='order.order_number', read_only=True)
    listing_title = serializers.CharField(
        source='listing.title', read_only=True)
    assigned_to_name = serializers.CharField(
        source='assigned_to.get_full_name', read_only=True)

    class Meta:
        model = SupportTicket
        fields = (
            'id', 'ticket_type', 'raised_by', 'raised_by_name',
            'raised_by_email', 'raised_by_role',
            'order', 'order_number', 'listing', 'listing_title',
            'subject', 'description', 'priority', 'status',
            'assigned_to', 'assigned_to_name',
            'resolution_notes', 'resolved_at',
            'created_at', 'updated_at',
        )
        read_only_fields = (
            'id', 'raised_by', 'resolved_at',
            'created_at', 'updated_at',
        )


class SupportTicketCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportTicket
        fields = (
            'ticket_type', 'order', 'listing',
            'subject', 'description', 'priority',
        )

    def validate(self, attrs):
        user = self.context['request'].user
        # Auto-detect raised_by_role from user role
        attrs['raised_by'] = user
        attrs['raised_by_role'] = (
            'vendor'
            if getattr(user, 'role', '') in ['seller', 'service_provider']
            else 'buyer'
        )
        return attrs


class MarkResolvedSerializer(serializers.Serializer):
    resolution_notes = serializers.CharField(required=False, allow_blank=True)


class SupportTicketSummarySerializer(serializers.Serializer):
    open_tickets = serializers.IntegerField()
    active_disputes = serializers.IntegerField()
    resolved_today = serializers.IntegerField()
    avg_resolution_time_hours = serializers.FloatField()
    open_change_percent = serializers.FloatField()
    disputes_change_percent = serializers.FloatField()
