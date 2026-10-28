from rest_framework import serializers

from apps.commerce.constants import SALES_STATUSES
from apps.commerce.models import OrderItem
from apps.listings.models import Listing

from .models import ListingReview, StoreReview


def _has_paid_order(user, *, listing=None, store=None):
    """A buyer may only review something they actually bought."""
    items = OrderItem.objects.filter(
        order__buyer=user,
        order__status__in=SALES_STATUSES,
    )
    if listing is not None:
        items = items.filter(listing=listing)
    if store is not None:
        items = items.filter(listing__store=store)
    return items.exists()


class ListingReviewSerializer(serializers.ModelSerializer):
    reviewer_name = serializers.SerializerMethodField()
    store_slug = serializers.CharField(source="listing.store.slug", read_only=True)
    listing_title = serializers.CharField(source="listing.title", read_only=True)

    def get_reviewer_name(self, obj) -> str:
        return getattr(obj.reviewer, "full_name", "") or obj.reviewer.get_full_name() or getattr(obj.reviewer, "username", "") or "Anonymous"

    class Meta:
        model = ListingReview
        fields = (
            "id",
            "listing",
            "listing_title",
            "store_slug",
            "reviewer",
            "reviewer_name",
            "rating",
            "comment",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "reviewer", "created_at", "updated_at")


class ListingReviewCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingReview
        fields = ("id", "listing", "rating", "comment")
        read_only_fields = ("id",)

    def validate_listing(self, value):
        if value.status != Listing.Status.PUBLISHED:
            raise serializers.ValidationError(
                "You can only review published listings."
            )
        return value

    def validate(self, attrs):
        request = self.context.get("request")
        listing = attrs.get("listing")
        if request and request.user.is_authenticated and listing:
            if listing.user_id == request.user.id:
                raise serializers.ValidationError(
                    "You cannot review your own listing."
                )
            if not _has_paid_order(request.user, listing=listing):
                raise serializers.ValidationError(
                    "You can only review a listing you have purchased."
                )
            if ListingReview.objects.filter(
                listing=listing, reviewer=request.user
            ).exists():
                raise serializers.ValidationError(
                    "You have already reviewed this listing."
                )
        return attrs

    def create(self, validated_data):
        validated_data["reviewer"] = self.context["request"].user
        return super().create(validated_data)


class StoreReviewSerializer(serializers.ModelSerializer):
    reviewer_name = serializers.SerializerMethodField()
    store_name = serializers.CharField(source="store.name", read_only=True)
    store_slug = serializers.CharField(source="store.slug", read_only=True)

    def get_reviewer_name(self, obj) -> str:
        return getattr(obj.reviewer, "full_name", "") or obj.reviewer.get_full_name() or getattr(obj.reviewer, "username", "") or "Anonymous"

    class Meta:
        model = StoreReview
        fields = (
            "id",
            "store",
            "store_name",
            "store_slug",
            "reviewer",
            "reviewer_name",
            "rating",
            "comment",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "reviewer", "created_at", "updated_at")


class StoreReviewCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = StoreReview
        fields = ("id", "store", "rating", "comment")
        read_only_fields = ("id",)

    def validate_store(self, value):
        if not value.is_published or not value.is_active:
            raise serializers.ValidationError(
                "You can only review active, published stores."
            )
        return value

    def validate(self, attrs):
        request = self.context.get("request")
        store = attrs.get("store")
        if request and request.user.is_authenticated and store:
            if store.user_id == request.user.id:
                raise serializers.ValidationError(
                    "You cannot review your own store."
                )
            if not _has_paid_order(request.user, store=store):
                raise serializers.ValidationError(
                    "You can only review a store you have purchased from."
                )
            if StoreReview.objects.filter(
                store=store, reviewer=request.user
            ).exists():
                raise serializers.ValidationError(
                    "You have already reviewed this store."
                )
        return attrs

    def create(self, validated_data):
        validated_data["reviewer"] = self.context["request"].user
        return super().create(validated_data)


class ListingReviewUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingReview
        fields = ("rating", "comment")


class StoreReviewUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = StoreReview
        fields = ("rating", "comment")
