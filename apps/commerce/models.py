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

    class Meta:
        db_table = "commerce_orders"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["order_type", "-placed_at"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return self.order_number
