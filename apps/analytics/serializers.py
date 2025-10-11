# apps/analytics/serializers.py
from rest_framework import serializers
from django.contrib.auth import get_user_model
from apps.categories.models import Category
from apps.listings.models import Listing
from drf_spectacular.utils import extend_schema_field

User = get_user_model()


class UserListSerializer(serializers.ModelSerializer):
    listings_count = serializers.IntegerField(
        source='listing_count', read_only=True, default=0)

    class Meta:
        model = User
        fields = ('id', 'email', 'first_name',
                  'last_name', 'role', 'listings_count')


class CategorySummarySerializer(serializers.ModelSerializer):
    listing_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Category
        fields = ('id', 'name', 'slug', 'listing_count')


class AnalyticsOverviewSerializer(serializers.Serializer):
    user_stats = serializers.DictField()
    listing_stats = serializers.DictField()
    inquiry_stats = serializers.DictField()
    category_stats = serializers.DictField()
    business_stats = serializers.DictField()
    generated_at = serializers.DateTimeField()


class ListingAnalyticsSerializer(serializers.Serializer):
    performance_metrics = serializers.DictField()
    popular_categories = CategorySummarySerializer(many=True)
    listing_trends = serializers.ListField()
    geographic_distribution = serializers.ListField()


class ConversionAnalyticsSerializer(serializers.Serializer):
    conversion_metrics = serializers.DictField()
    response_metrics = serializers.DictField()


class UserAnalyticsSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "role",
            "is_active",
            "is_verified",
            "date_joined",
            "last_login",
        ]

    @extend_schema_field(str)
    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()


class AnalyticsOverviewSerializer(serializers.Serializer):
    """Serializer for high-level analytics summary (optional helper)."""

    user_stats = serializers.DictField()
    listing_stats = serializers.DictField()
    inquiry_stats = serializers.DictField()
    category_stats = serializers.DictField()
    business_stats = serializers.DictField()
    generated_at = serializers.DateTimeField()
