from rest_framework import serializers
from django.contrib.contenttypes.models import ContentType

from .models import ReportedContent, AdminActionLog, PlatformConfig


class ReportedContentSerializer(serializers.ModelSerializer):
    """Full serializer for listing, detail, and admin review of reported content."""
    reported_by_email = serializers.CharField(
        source="reported_by.email", read_only=True
    )
    reviewed_by_email = serializers.CharField(
        source="reviewed_by.email", read_only=True
    )

    class Meta:
        model = ReportedContent
        fields = "__all__"
        read_only_fields = (
            "id",
            "reported_by",
            "created_at",
            "reviewed_at",
        )


REPORTABLE_TYPES = [
    ('listing', 'Listing'),
    ('user', 'User'),
    ('inquiry', 'Inquiry'),
]


class ReportedContentCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating content reports"""
    content_type = serializers.ChoiceField(
        choices=REPORTABLE_TYPES,
        help_text="The type of content being reported: listing, user, or inquiry"
    )

    class Meta:
        model = ReportedContent
        fields = ('content_type', 'object_id', 'reason', 'description')

    def validate(self, attrs):
        """Validate and map content_type string to ContentType instance"""
        content_type_str = attrs['content_type']
        object_id = attrs['object_id']

        model_map = {
            'listing': 'listings.Listing',
            'user': 'accounts.User',
            'inquiry': 'inquiries.Inquiry',
        }

        if content_type_str not in model_map:
            raise serializers.ValidationError("Invalid content type.")

        try:
            app_label, model_name = model_map[content_type_str].split('.')
            content_type = ContentType.objects.get(
                app_label=app_label, model=model_name.lower())
        except ContentType.DoesNotExist:
            raise serializers.ValidationError("Invalid content type mapping.")

        # Replace content_type string with actual instance for save()
        attrs['content_type'] = content_type

        # Validate that object exists
        model_class = content_type.model_class()
        if not model_class.objects.filter(pk=object_id).exists():
            raise serializers.ValidationError(
                "Reported content does not exist.")

        # Prevent duplicate reports
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            duplicate = ReportedContent.objects.filter(
                reported_by=request.user,
                content_type=content_type,
                object_id=object_id,
                status__in=[
                    ReportedContent.Status.PENDING,
                    ReportedContent.Status.REVIEWED,
                ],
            ).exists()
            if duplicate:
                raise serializers.ValidationError(
                    "You have already reported this content.")
        else:
            raise serializers.ValidationError("Authentication required.")

        return attrs


class PlatformConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformConfig
        exclude = ('updated_by',)
        read_only_fields = ('id', 'updated_at')


class AdminOrderListSerializer(serializers.ModelSerializer):
    buyer_name = serializers.CharField(source='buyer.full_name', read_only=True)
    buyer_email = serializers.EmailField(source='buyer.email', read_only=True)
    listing_title = serializers.CharField(
        source='listing.title', read_only=True)
    amount = serializers.DecimalField(
        source='total_amount', max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = __import__('apps.commerce.models', fromlist=['Order']).Order
        fields = (
            'id', 'order_number', 'buyer_name', 'buyer_email',
            'listing_title', 'amount', 'currency', 'status', 'created_at'
        )
        read_only_fields = fields


class AdminActionLogSerializer(serializers.ModelSerializer):
    admin_user_email = serializers.EmailField(
        source='admin_user.email', read_only=True)
    action_type_display = serializers.CharField(
        source='get_action_type_display', read_only=True)

    class Meta:
        model = AdminActionLog
        fields = (
            'id', 'admin_user', 'admin_user_email',
            'action_type', 'action_type_display',
            'description', 'timestamp', 'extra_data'
        )
        read_only_fields = ('id', 'timestamp')
