from rest_framework import serializers

from apps.listings.models import Listing

from .models import ListingReview, StoreReview


class ListingReviewSerializer(serializers.ModelSerializer):
    reviewer_name = serializers.CharField(
        source="reviewer.get_full_name", read_only=True
    )

    class Meta:
        model = ListingReview
        fields = (
            "id",
            "listing",
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
        fields = ("listing", "rating", "comment")

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
    reviewer_name = serializers.CharField(
        source="reviewer.get_full_name", read_only=True
    )

    class Meta:
        model = StoreReview
        fields = (
            "id",
            "store",
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
        fields = ("store", "rating", "comment")

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
