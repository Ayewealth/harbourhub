import uuid

from django.utils import timezone
from rest_framework import serializers

from apps.listings.models import Listing

from .models import Order, QuoteRequest


class QuoteRequestCreateSerializer(serializers.ModelSerializer):
    purchase_type = serializers.ChoiceField(
        choices=QuoteRequest.PurchaseType.choices
    )
    duration_bucket = serializers.ChoiceField(
        choices=QuoteRequest.DurationBucket.choices,
        required=False,
        allow_blank=True,
    )

    class Meta:
        model = QuoteRequest
        fields = (
            "listing",
            "store",
            "purchase_type",
            "quantity",
            "duration_bucket",
            "preferred_delivery_date",
            "delivery_location",
            "notes",
        )

    def validate_listing(self, value):
        if value.status != Listing.Status.PUBLISHED:
            raise serializers.ValidationError("Listing must be published.")
        return value

    def create(self, validated_data):
        validated_data["buyer"] = self.context["request"].user
        return super().create(validated_data)


class QuoteRequestSerializer(serializers.ModelSerializer):
    listing_title = serializers.CharField(
        source="listing.title", read_only=True)
    buyer_email = serializers.EmailField(source="buyer.email", read_only=True)

    class Meta:
        model = QuoteRequest
        fields = (
            "id",
            "listing",
            "listing_title",
            "buyer",
            "buyer_email",
            "store",
            "purchase_type",
            "quantity",
            "duration_bucket",
            "preferred_delivery_date",
            "delivery_location",
            "notes",
            "status",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("buyer", "status", "created_at", "updated_at")


class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = (
            "id",
            "order_number",
            "order_type",
            "buyer",
            "seller",
            "listing",
            "store",
            "currency",
            "total_amount",
            "status",
            "placed_at",
            "quote_request",
            "extra",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("order_number", "created_at", "updated_at")


class OrderCreateSerializer(serializers.ModelSerializer):
    order_type = serializers.ChoiceField(
        choices=Order.OrderType.choices
    )
    status = serializers.ChoiceField(
        choices=Order.Status.choices,
        required=False,
    )

    class Meta:
        model = Order
        fields = (
            "order_type",
            "buyer",
            "seller",
            "listing",
            "store",
            "currency",
            "total_amount",
            "status",
            "placed_at",
            "quote_request",
            "extra",
        )

    def validate(self, attrs):
        # auto-set buyer from request
        attrs['buyer'] = self.context['request'].user

        # if created from a quote, validate it belongs to this buyer
        quote = attrs.get('quote_request')
        if quote and quote.buyer != attrs['buyer']:
            raise serializers.ValidationError("Quote does not belong to you.")
        return attrs

    def create(self, validated_data):
        validated_data.setdefault(
            "order_number", f"ORD-{uuid.uuid4().hex[:12].upper()}")
        if not validated_data.get("placed_at") and validated_data.get("status") not in (Order.Status.DRAFT,):
            validated_data["placed_at"] = timezone.now()
        return super().create(validated_data)
