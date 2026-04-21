from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class QuoteRequest(models.Model):
    """Request-a-quote flow (listing + vendor context, date-range friendly)."""

    class PurchaseType(models.TextChoices):
        BUY = "buy", _("Buy")
        RENT = "rent", _("Rent")

    class DurationBucket(models.TextChoices):
        D1_50 = "1_50_days", _("1 – 50 days")
        D50_100 = "50_100_days", _("50 – 100 days")
        D100_150 = "100_150_days", _("100 – 150 days")

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        RESPONDED = "responded", _("Responded")
        CANCELLED = "cancelled", _("Cancelled")
        CONVERTED = "converted", _("Converted to order")

    listing = models.ForeignKey(
        "listings.Listing",
        on_delete=models.CASCADE,
        related_name="quote_requests",
    )
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="quote_requests",
    )
    store = models.ForeignKey(
        "store.Store",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="quote_requests",
        help_text=_("Vendor store receiving the quote"),
    )
    purchase_type = models.CharField(
        max_length=10,
        choices=PurchaseType.choices,
    )
    quantity = models.PositiveIntegerField(default=1)
    duration_bucket = models.CharField(
        max_length=32,
        choices=DurationBucket.choices,
        blank=True,
    )
    preferred_delivery_date = models.DateField(null=True, blank=True)
    delivery_location = models.CharField(max_length=500, blank=True)
    notes = models.TextField(blank=True)
    vendor_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Vendor's counter-offer price (overrides listing price for this quote)"),
    )
    vendor_notes = models.TextField(
        blank=True,
        help_text=_("Additional notes from the vendor to the buyer"),
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "quote_requests"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self):
        return f"Quote {self.pk} for listing {self.listing_id}"


class Order(models.Model):
    """Orders used for marketplace breakdown (buy / hire / lease)."""

    class OrderType(models.TextChoices):
        BUY = "buy", _("Buy transaction")
        HIRE = "hire", _("Hire booking")
        LEASE = "lease", _("Lease contract")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PENDING_PAYMENT = "pending_payment", _("Pending payment")
        PAID = "paid", _("Paid")
        FULFILLED = "fulfilled", _("Fulfilled")
        CANCELLED = "cancelled", _("Cancelled")

    order_number = models.CharField(max_length=40, unique=True, db_index=True)
    order_type = models.CharField(
        max_length=16,
        choices=OrderType.choices,
        db_index=True,
    )
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders_as_buyer",
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders_as_seller",
    )
    listing = models.ForeignKey(
        "listings.Listing",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    store = models.ForeignKey(
        "store.Store",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    currency = models.CharField(max_length=3, default="NGN")
    total_amount = models.DecimalField(max_digits=14, decimal_places=2)
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    placed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    quote_request = models.ForeignKey(
        QuoteRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    extra = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Rental tracking (for hire/lease orders)
    rental_start_date = models.DateField(null=True, blank=True)
    rental_end_date = models.DateField(null=True, blank=True)
    pickup_scheduled_date = models.DateField(null=True, blank=True)

    # Delivery info
    delivery_address = models.TextField(blank=True)
    delivery_contact_name = models.CharField(max_length=100, blank=True)
    delivery_contact_phone = models.CharField(max_length=30, blank=True)
    delivery_carrier = models.CharField(max_length=100, blank=True)
    tracking_id = models.CharField(max_length=100, blank=True)

    # Escrow
    escrow_fee = models.DecimalField(
        max_digits=14, decimal_places=2, default=0)
    subtotal = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True)
    delivery_fee = models.DecimalField(
        max_digits=14, decimal_places=2, default=0)

    @property
    def rental_days_total(self):
        if self.rental_start_date and self.rental_end_date:
            return (self.rental_end_date - self.rental_start_date).days
        return None

    @property
    def rental_days_elapsed(self):
        if not self.rental_start_date:
            return None
        from django.utils import timezone
        today = timezone.now().date()
        elapsed = (today - self.rental_start_date).days
        return min(elapsed, self.rental_days_total or elapsed)

    @property
    def rental_progress_percentage(self):
        total = self.rental_days_total
        elapsed = self.rental_days_elapsed
        if total and elapsed is not None:
            return round((elapsed / total) * 100, 1)
        return 0

    class Meta:
        db_table = "commerce_orders"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["order_type", "-placed_at"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return self.order_number


class OrderActivity(models.Model):
    """Timeline events for an order."""

    class EventType(models.TextChoices):
        ORDER_PLACED = 'order_placed', _('Order Placed')
        PAYMENT_CONFIRMED = 'payment_confirmed', _('Payment Confirmed')
        RENTAL_APPROVED = 'rental_approved', _('Rental Approved')
        READY_FOR_DISPATCH = 'ready_for_dispatch', _('Ready for Dispatch')
        SHIPPED = 'shipped', _('Shipped')
        IN_TRANSIT = 'in_transit', _('In Transit')
        DELIVERED = 'delivered', _('Delivered')
        RENTAL_PERIOD_ACTIVE = 'rental_period_active', _(
            'Rental Period Active')
        RENTAL_PERIOD_ENDING = 'rental_period_ending', _(
            'Rental Period Ending Soon')
        RENTAL_EXTENDED = 'rental_extended', _('Rental Extended')
        EQUIPMENT_COLLECTED = 'equipment_collected', _('Equipment Collected')
        VENDOR_CONFIRMED_RETURN = 'vendor_confirmed_return', _(
            'Vendor Confirmed Return')
        ORDER_COMPLETED = 'order_completed', _('Order Completed')
        ORDER_CANCELLED = 'order_cancelled', _('Order Cancelled')

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='activities'
    )
    event_type = models.CharField(max_length=50, choices=EventType.choices)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'order_activities'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.event_type} for order {self.order.order_number}"


class Cart(models.Model):
    """Shopping cart for a buyer."""
    buyer = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='cart'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'carts'

    def __str__(self):
        return f"Cart for {self.buyer.email}"

    @property
    def total(self):
        return sum(item.subtotal for item in self.items.all())

    @property
    def item_count(self):
        return self.items.count()


class CartItem(models.Model):
    """Individual item in a cart."""

    class PurchaseType(models.TextChoices):
        BUY = 'buy', _('Buy')
        RENT = 'rent', _('Rent')
        LEASE = 'lease', _('Lease')

    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name='items'
    )
    listing = models.ForeignKey(
        'listings.Listing',
        on_delete=models.CASCADE,
        related_name='cart_items'
    )
    store = models.ForeignKey(
        'store.Store',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='cart_items'
    )
    purchase_type = models.CharField(
        max_length=10,
        choices=PurchaseType.choices,
        default=PurchaseType.BUY
    )
    quantity = models.PositiveIntegerField(default=1)
    duration_days = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="For rent/lease orders"
    )
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'cart_items'
        unique_together = [['cart', 'listing', 'purchase_type']]

    @property
    def subtotal(self):
        if self.purchase_type == self.PurchaseType.BUY:
            return self.unit_price * self.quantity
        # For rent/lease multiply by days
        days = self.duration_days or 1
        return self.unit_price * self.quantity * days

    def __str__(self):
        return f"{self.listing.title} in cart"


class Payment(models.Model):
    """Payment record linked to an order."""

    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        SUCCESS = 'success', _('Success')
        FAILED = 'failed', _('Failed')
        REFUNDED = 'refunded', _('Refunded')

    class Gateway(models.TextChoices):
        PAYSTACK = 'paystack', _('Paystack')

    order = models.OneToOneField(
        Order,
        on_delete=models.CASCADE,
        related_name='payment'
    )
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payments'
    )
    gateway = models.CharField(
        max_length=20,
        choices=Gateway.choices,
        default=Gateway.PAYSTACK
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, default='NGN')
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True
    )
    reference = models.CharField(
        max_length=100, unique=True,
        help_text="Paystack payment reference"
    )
    paystack_access_code = models.CharField(max_length=100, blank=True)
    authorization_url = models.URLField(blank=True)
    gateway_response = models.JSONField(default=dict, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payments'
        ordering = ['-created_at']

    def __str__(self):
        return f"Payment {self.reference} - {self.status}"
