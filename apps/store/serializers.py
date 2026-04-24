from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from .models import Store
from apps.accounts.serializers import UserProfileSerializer
from apps.listings.models import Listing, ListingImage


class ListingImageMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingImage
        fields = (
            "id",
            "image",
        )


class StoreListingMiniSerializer(serializers.ModelSerializer):
    price_display = serializers.CharField(read_only=True)
    primary_image = serializers.SerializerMethodField()

    class Meta:
        model = Listing
        fields = (
            "id",
            "title",
            "slug",
            "listing_type",
            "price",
            "currency",
            "price_display",
            "location",
            "featured",
            "status",
            "created_at",
            "primary_image",
        )

    @extend_schema_field(ListingImageMiniSerializer)
    def get_primary_image(self, obj):
        primary = obj.images.filter(is_primary=True).first()
        if primary:
            return ListingImageMiniSerializer(primary).data

        fallback = obj.images.first()
        if fallback:
            return ListingImageMiniSerializer(fallback).data

        return None


class StoreDirectoryListingPreviewMixin(serializers.Serializer):
    """Shared listing preview + count for directory list and public storefront detail."""

    listing_count = serializers.SerializerMethodField()
    listings = serializers.SerializerMethodField()

    @extend_schema_field(serializers.IntegerField())
    def get_listing_count(self, obj):
        return obj.listings.filter(status=Listing.Status.PUBLISHED).count()

    @extend_schema_field(StoreListingMiniSerializer(many=True))
    def get_listings(self, obj):
        limit = self.context.get("listing_limit", 6)

        featured_list = list(
            obj.listings.filter(
                status=Listing.Status.PUBLISHED,
                featured=True
            ).order_by("-created_at")[:limit]
        )

        remaining = limit - len(featured_list)

        if remaining > 0:
            featured_ids = [item.id for item in featured_list]

            recent_list = list(
                obj.listings.filter(
                    status=Listing.Status.PUBLISHED
                ).exclude(
                    id__in=featured_ids
                ).order_by("-created_at")[:remaining]
            )

            listings = featured_list + recent_list
        else:
            listings = featured_list

        return StoreListingMiniSerializer(listings, many=True).data


class StoreRatingStatsMixin(serializers.Serializer):
    """Optional aggregates from queryset annotation (`rating_avg`, `review_count`)."""

    rating_average = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()

    @extend_schema_field(serializers.FloatField(allow_null=True))
    def get_rating_average(self, obj):
        v = getattr(obj, "rating_avg", None)
        if v is None:
            return None
        return round(float(v), 2)

    @extend_schema_field(serializers.IntegerField())
    def get_review_count(self, obj):
        v = getattr(obj, "review_count", None)
        return int(v) if v is not None else 0


class StoreListSerializer(
    StoreRatingStatsMixin,
    StoreDirectoryListingPreviewMixin,
    serializers.ModelSerializer,
):
    """Vendor directory card: store + owner + listing preview."""

    user = UserProfileSerializer(read_only=True)
    categories = serializers.StringRelatedField(many=True, read_only=True)

    class Meta:
        model = Store
        fields = (
            "id",
            "user",
            "slug",
            "name",
            "description",
            "logo",
            "banner_image",
            "city",
            "state",
            "country",
            "categories",
            "is_active",
            "is_published",
            "rating_average",
            "review_count",
            "listing_count",
            "listings",
            "created_at",
            "updated_at",
        )


class StoreCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a store"""
    class Meta:
        model = Store
        fields = '__all__'
        read_only_fields = ('user', 'is_verified', 'is_active',
                            'is_published', 'created_at', 'updated_at')


class StoreUpdateSerializer(serializers.ModelSerializer):
    commission_rate = serializers.DecimalField(
        max_digits=5, decimal_places=2, read_only=True)

    class Meta:
        model = Store
        fields = '__all__'
        read_only_fields = ('user', 'is_verified', 'created_at', 'updated_at')


class StoreDetailSerializer(
    StoreRatingStatsMixin,
    StoreDirectoryListingPreviewMixin,
    serializers.ModelSerializer,
):
    """Public storefront page: full profile fields + listing preview."""

    user = UserProfileSerializer(read_only=True)
    categories = serializers.StringRelatedField(many=True, read_only=True)
    commission_rate = serializers.DecimalField(
        max_digits=5, decimal_places=2, read_only=True)

    class Meta:
        model = Store
        fields = (
            "id",
            "user",
            "slug",
            "categories",
            "name",
            "description",
            "banner_image",
            "logo",
            "email",
            "phone",
            "address",
            "city",
            "state",
            "country",
            "commission_rate",
            "zip_code",
            "policy",
            "is_active",
            "is_published",
            "rating_average",
            "review_count",
            "listing_count",
            "listings",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("user", "is_verified", "is_active",
                            "is_published", "created_at", "updated_at")
