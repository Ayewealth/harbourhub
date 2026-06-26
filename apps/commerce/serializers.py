import uuid

from django.utils import timezone
from rest_framework import serializers

from apps.core.currency import CurrencyConverterMixin
from apps.listings.models import Listing

from .models import Cart, CartItem, Order, OrderActivity, Payment, QuoteRequest


class QuoteRequestCreateSerializer(serializers.ModelSerializer):
    purchase_type = serializers.ChoiceField(
        choices=QuoteRequest.PurchaseType.choices
    )

    class Meta:
        model = QuoteRequest
        fields = (
            "listing",
            "store",
            "purchase_type",
            "quantity",
            "duration_days",
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


class QuoteRequestSerializer(CurrencyConverterMixin, serializers.ModelSerializer):
    monetary_fields = ["vendor_price"]
    listing_title = serializers.CharField(
        source="listing.title", read_only=True)
    buyer_email = serializers.EmailField(source="buyer.email", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    store_slug = serializers.CharField(source="store.slug", read_only=True)
    currency = serializers.CharField(source="listing.currency", read_only=True)

    class Meta:
        model = QuoteRequest
        fields = (
            "id",
            "listing",
            "listing_title",
            "buyer",
            "buyer_email",
            "store",
            "store_name",
            "store_slug",
            "purchase_type",
            "quantity",
            "duration_days",
            "preferred_delivery_date",
            "delivery_location",
            "notes",
            "vendor_price",
            "vendor_notes",
            "currency",
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


class OrderSerializer(CurrencyConverterMixin, serializers.ModelSerializer):
    monetary_fields = ["subtotal", "delivery_fee", "escrow_fee", "total_amount"]

    activities = OrderActivitySerializer(many=True, read_only=True)
    rental_days_total = serializers.IntegerField(read_only=True)
    rental_days_elapsed = serializers.IntegerField(read_only=True)
    rental_progress_percentage = serializers.FloatField(read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    store_slug = serializers.CharField(source="store.slug", read_only=True)
    carrier = serializers.CharField(source="delivery_carrier", read_only=True)

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
            "store_name",
            "store_slug",
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
            "carrier",
            "rental_start_date",
            "rental_end_date",
            "rental_duration_days",
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


class OrderCreateSerializer(CurrencyConverterMixin, serializers.ModelSerializer):
    monetary_fields = ["total_amount"]

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


class CartItemSerializer(CurrencyConverterMixin, serializers.ModelSerializer):
    monetary_fields = ["listing_price", "unit_price", "subtotal"]

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
            'unit_price', 'subtotal', 'quote_request', 'created_at',
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


class CartSerializer(CurrencyConverterMixin, serializers.ModelSerializer):
    monetary_fields = ["total"]

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


# ─── Order Tracking & Timelines Serializers ──────────────────────────────────
from apps.core.currency import CurrencyConverterMixin


class OrderTrackingTimelineSerializer(serializers.ModelSerializer):
    event = serializers.CharField(source="event_type")
    label = serializers.CharField(source="get_event_type_display")
    description = serializers.CharField(source="message")
    actor = serializers.SerializerMethodField()
    actor_name = serializers.SerializerMethodField()
    timestamp = serializers.DateTimeField(source="created_at")
    is_current = serializers.SerializerMethodField()

    class Meta:
        model = OrderActivity
        fields = (
            "event",
            "label",
            "description",
            "actor",
            "actor_name",
            "timestamp",
            "is_current",
        )

    def get_actor(self, obj):
        evt = obj.event_type
        if evt in ['order_placed', 'dispute_opened', 'item_returned']:
            return "buyer"
        elif evt in ['order_confirmed', 'item_dispatched', 'in_transit', 'delivered']:
            return "seller"
        elif evt in ['dispute_resolved', 'order_refunded']:
            return "admin"
        else:
            return "system"

    def get_actor_name(self, obj):
        actor = self.get_actor(obj)
        if actor == "buyer":
            return obj.order.buyer.full_name or obj.order.buyer.email
        elif actor == "seller":
            return obj.order.store.name if obj.order.store else (obj.order.seller.full_name or obj.order.seller.email)
        elif actor == "admin":
            return "Platform Admin"
        return None

    def get_is_current(self, obj):
        # We set this dynamically in the view to true for the most recent timeline entry only
        return getattr(obj, "is_current", False)


class OrderTrackingDetailSerializer(CurrencyConverterMixin, serializers.ModelSerializer):
    monetary_fields = ["total_amount", "subtotal", "delivery_fee", "escrow_fee"]

    order_id = serializers.CharField(source="order_number")
    listing_title = serializers.CharField(source="listing.title", default="")
    buyer = serializers.SerializerMethodField()
    seller = serializers.SerializerMethodField()
    rental_start = serializers.DateField(source="rental_start_date", allow_null=True)
    rental_end = serializers.DateField(source="rental_end_date", allow_null=True)
    rental_duration = serializers.IntegerField(source="rental_duration_days", read_only=True, allow_null=True)
    dispute = serializers.SerializerMethodField()
    timeline = serializers.SerializerMethodField()
    carrier = serializers.CharField(source="delivery_carrier", read_only=True)
    estimated_delivery = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = (
            "order_id",
            "status",
            "order_type",
            "listing_title",
            "buyer",
            "seller",
            "created_at",
            "estimated_delivery",
            "rental_start",
            "rental_end",
            "rental_duration",
            "dispute",
            "timeline",
            "tracking_id",
            "delivery_carrier",
            "carrier",
        )

    def get_buyer(self, obj):
        return {
            "name": obj.buyer.full_name or obj.buyer.username,
            "email": obj.buyer.email
        }

    def get_seller(self, obj):
        return {
            "name": obj.store.name if obj.store else (obj.seller.full_name or obj.seller.username),
            "store_slug": obj.store.slug if obj.store else ""
        }

    def get_dispute(self, obj):
        disp = obj.disputes.first()
        if disp:
            return {
                "id": disp.id,
                "status": disp.status,
                "opened_at": disp.created_at
            }
        return None

    def get_timeline(self, obj):
        activities = list(obj.activities.all().order_by("created_at"))
        if activities:
            # Mark the last one as current
            for act in activities:
                act.is_current = False
            activities[-1].is_current = True
        return OrderTrackingTimelineSerializer(activities, many=True).data

    def get_estimated_delivery(self, obj):
        from datetime import timedelta
        if obj.created_at:
            return obj.created_at + timedelta(days=7)
        return None


class AdminOrderTrackingSerializer(OrderTrackingDetailSerializer):
    escrow_status = serializers.SerializerMethodField()
    vendor_earning_status = serializers.SerializerMethodField()
    dispute_detail = serializers.SerializerMethodField()
    internal_notes = serializers.SerializerMethodField()

    class Meta(OrderTrackingDetailSerializer.Meta):
        fields = OrderTrackingDetailSerializer.Meta.fields + (
            "escrow_status",
            "vendor_earning_status",
            "dispute_detail",
            "internal_notes",
        )

    def get_escrow_status(self, obj):
        disp = obj.disputes.first()
        if disp:
            if disp.status in ['resolved', 'refunded']:
                return "released"
            return "held"
        if obj.status == Order.Status.FULFILLED:
            return "released"
        return "held"

    def get_vendor_earning_status(self, obj):
        if hasattr(obj, "earning"):
            return obj.earning.status
        return "pending"

    def get_dispute_detail(self, obj):
        disp = obj.disputes.first()
        if disp:
            return {
                "id": disp.id,
                "status": disp.status,
                "reason": disp.reason,
                "opened_by": disp.buyer.full_name or disp.buyer.email,
                "opened_at": disp.created_at,
                "resolution": disp.resolution_notes or None,
            }
        return None

    def get_internal_notes(self, obj):
        # Admin can add notes, let's return from disputes or order activities
        notes = []
        disp = obj.disputes.first()
        if disp and disp.resolution_notes:
            notes.append(f"Dispute resolution note: {disp.resolution_notes}")
        return notes


class OrderListTrackingSummarySerializer(serializers.ModelSerializer):
    order_id = serializers.CharField(source="order_number")
    listing_title = serializers.CharField(source="listing.title", default="")
    seller_name = serializers.CharField(source="store.name", default="")
    buyer_name = serializers.CharField(source="buyer.full_name", default="")
    last_event = serializers.SerializerMethodField()
    last_event_at = serializers.SerializerMethodField()
    carrier = serializers.CharField(source="delivery_carrier", read_only=True)

    class Meta:
        model = Order
        fields = (
            "order_id",
            "listing_title",
            "seller_name",
            "buyer_name",
            "order_type",
            "status",
            "last_event",
            "last_event_at",
            "created_at",
            "tracking_id",
            "delivery_carrier",
            "carrier",
        )

    def get_last_event(self, obj):
        last_act = obj.activities.all().order_by("-created_at").first()
        if last_act:
            return last_act.message
        return "Order Placed"

    def get_last_event_at(self, obj):
        last_act = obj.activities.all().order_by("-created_at").first()
        if last_act:
            return last_act.created_at
        return obj.created_at

