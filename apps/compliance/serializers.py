from rest_framework import serializers
from .models import ComplianceDocument


class ComplianceDocumentSerializer(serializers.ModelSerializer):
    party_name = serializers.CharField(
        source='party.get_full_name', read_only=True)
    party_email = serializers.EmailField(
        source='party.email', read_only=True)
    order_number = serializers.CharField(
        source='order.order_number', read_only=True)
    listing_title = serializers.CharField(
        source='listing.title', read_only=True)
    days_remaining = serializers.IntegerField(read_only=True)
    reviewed_by_name = serializers.CharField(
        source='reviewed_by.get_full_name', read_only=True)

    class Meta:
        model = ComplianceDocument
        fields = (
            'id', 'document_type', 'party', 'party_name',
            'party_email', 'party_role',
            'order', 'order_number', 'listing', 'listing_title',
            'name', 'file', 'status', 'start_date', 'end_date',
            'days_remaining', 'is_verified', 'verified_at',
            'reviewed_by', 'reviewed_by_name', 'reviewed_at',
            'admin_notes', 'created_at', 'updated_at',
        )
        read_only_fields = (
            'id', 'days_remaining', 'verified_at',
            'reviewed_at', 'created_at', 'updated_at',
        )


class ComplianceDocumentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComplianceDocument
        fields = (
            'document_type', 'order', 'listing',
            'name', 'file', 'start_date', 'end_date',
        )

    def validate(self, attrs):
        user = self.context['request'].user
        attrs['party'] = user
        attrs['party_role'] = (
            'vendor'
            if getattr(user, 'role', '') in ['seller', 'service_provider']
            else 'buyer'
        )
        return attrs


class VerifyDocumentSerializer(serializers.Serializer):
    is_verified = serializers.BooleanField()
    admin_notes = serializers.CharField(required=False, allow_blank=True)


class ComplianceSummarySerializer(serializers.Serializer):
    active_contracts = serializers.IntegerField()
    expiring_soon = serializers.IntegerField()
    expired = serializers.IntegerField()
    missing_certifications = serializers.IntegerField()
    active_change_percent = serializers.FloatField()
    expiring_change_percent = serializers.FloatField()
