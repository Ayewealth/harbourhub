from .models import Cart, CartItem, OrderActivity, Order, Payment
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
            "vendor_price",
            "vendor_notes",
            "status",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("buyer", "status", "created_at", "updated_at")


class QuoteRequestVendorUpdateSerializer(serializers.ModelSerializer):
    """Vendor-only update: counter-offer price and notes."""

    class Meta:
        model = QuoteRequest
        fields = ("vendor_price", "vendor_notes")


class OrderActivitySerializer(serializers.ModelSerializer):
    event_type_display = serializers.CharField(
        source='get_event_type_display', read_only=True
    )

    class Meta:
        model = OrderActivity
        fields = (
            'id',
            'order',
            'event_type',
            'event_type_display',
            'message',
            'created_at',
        )
        read_only_fields = ('id', 'order', 'created_at')


class OrderSerializer(serializers.ModelSerializer):
    activities = OrderActivitySerializer(many=True, read_only=True)
    rental_days_total = serializers.IntegerField(read_only=True)
    rental_days_elapsed = serializers.IntegerField(read_only=True)
    rental_progress_percentage = serializers.FloatField(read_only=True)

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
            "subtotal",
            "delivery_fee",
            "escrow_fee",
            "total_amount",
            "status",
            "placed_at",
            "quote_request",
            "tracking_id",
            "delivery_address",
            "delivery_contact_name",
            "delivery_contact_phone",
            "delivery_carrier",
            "rental_start_date",
            "rental_end_date",
            "pickup_scheduled_date",
            "rental_days_total",
            "rental_days_elapsed",
            "rental_progress_percentage",
            "activities",
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


class CartItemSerializer(serializers.ModelSerializer):
    listing_title = serializers.CharField(
        source='listing.title', read_only=True)
    listing_price = serializers.DecimalField(
        source='listing.price',
        max_digits=14, decimal_places=2,
        read_only=True
    )
    primary_image = serializers.SerializerMethodField()
    store_name = serializers.CharField(
        source='store.name', read_only=True)
    subtotal = serializers.DecimalField(
        max_digits=14, decimal_places=2,
        read_only=True
    )

    class Meta:
        model = CartItem
        fields = (
            'id', 'listing', 'listing_title', 'listing_price',
            'primary_image', 'store', 'store_name',
            'purchase_type', 'quantity', 'duration_days',
            'unit_price', 'subtotal', 'created_at',
        )
        read_only_fields = ('id', 'unit_price', 'subtotal', 'created_at')

    def get_primary_image(self, obj):
        primary = obj.listing.images.filter(is_primary=True).first()
        if primary:
            request = self.context.get('request')
            return request.build_absolute_uri(
                primary.image.url) if request else primary.image.url
        return None


class CartItemCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CartItem
        fields = (
            'listing', 'purchase_type',
            'quantity', 'duration_days',
        )

    def validate_listing(self, value):
        from apps.listings.models import Listing
        if value.status != Listing.Status.PUBLISHED:
            raise serializers.ValidationError(
                "This listing is not available.")
        return value

    def validate(self, attrs):
        listing = attrs['listing']
        purchase_type = attrs.get('purchase_type', CartItem.PurchaseType.BUY)

        # Validate duration for rent/lease
        if purchase_type in [
            CartItem.PurchaseType.RENT,
            CartItem.PurchaseType.LEASE
        ] and not attrs.get('duration_days'):
            raise serializers.ValidationError(
                "duration_days is required for rent/lease.")

        # Set unit price from listing
        attrs['unit_price'] = listing.price or 0
        attrs['store'] = listing.store
        return attrs

    def create(self, validated_data):
        cart = self.context['cart']
        listing = validated_data['listing']
        purchase_type = validated_data.get(
            'purchase_type', CartItem.PurchaseType.BUY)

        # Update if exists
        item, created = CartItem.objects.update_or_create(
            cart=cart,
            listing=listing,
            purchase_type=purchase_type,
            defaults={
                'quantity': validated_data.get('quantity', 1),
                'duration_days': validated_data.get('duration_days'),
                'unit_price': validated_data['unit_price'],
                'store': validated_data.get('store'),
            }
        )
        return item


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    total = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True)
    item_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Cart
        fields = ('id', 'items', 'total', 'item_count', 'updated_at')


class CheckoutSerializer(serializers.Serializer):
    """Converts cart items into an order and initiates payment."""
    cart_item_ids = serializers.ListField(
        child=serializers.IntegerField(),
        help_text="IDs of cart items to checkout"
    )
    delivery_detail_id = serializers.IntegerField(
        help_text="ID of saved delivery address"
    )
    payment_method = serializers.ChoiceField(
        choices=[('paystack', 'Paystack')],
        default='paystack'
    )
    terms_accepted = serializers.BooleanField()

    def validate_terms_accepted(self, value):
        if not value:
            raise serializers.ValidationError(
                "You must accept the terms and conditions.")
        return value

    def validate_delivery_detail_id(self, value):
        from apps.accounts.models import DeliveryDetail
        user = self.context['request'].user
        try:
            self.delivery_detail = DeliveryDetail.objects.get(
                pk=value, user=user)
        except DeliveryDetail.DoesNotExist:
            raise serializers.ValidationError(
                "Delivery address not found.")
        return value

    def validate_cart_item_ids(self, value):
        if not value:
            raise serializers.ValidationError(
                "At least one cart item is required.")
        return value

    def validate(self, attrs):
        user = self.context['request'].user
        cart_item_ids = attrs['cart_item_ids']

        try:
            cart = Cart.objects.get(buyer=user)
        except Cart.DoesNotExist:
            raise serializers.ValidationError("Cart is empty.")

        items = cart.items.filter(
            id__in=cart_item_ids
        ).select_related('listing', 'store')

        if not items.exists():
            raise serializers.ValidationError(
                "No valid cart items found.")

        attrs['cart_items'] = items
        return attrs


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = (
            'id', 'order', 'amount', 'currency',
            'status', 'reference', 'authorization_url',
            'paid_at', 'created_at',
        )
        read_only_fields = fields


class DisputeSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source='order.order_number', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = __import__('apps.commerce.models', fromlist=['Dispute']).Dispute
        fields = (
            'id', 'order', 'order_number', 'buyer', 'reason',
            'description', 'status', 'status_display',
            'resolution_notes', 'resolved_at', 'created_at',
            'updated_at'
        )
        read_only_fields = ('buyer', 'status', 'resolution_notes', 'resolved_at', 'created_at', 'updated_at')

    def create(self, validated_data):
        validated_data['buyer'] = self.context['request'].user
        return super().create(validated_data)


class DisputeResolutionSerializer(serializers.Serializer):
    """Admin-only: resolve or refund a dispute."""
    action = serializers.ChoiceField(choices=['resolve', 'refund'])
    resolution_notes = serializers.CharField(required=True)
