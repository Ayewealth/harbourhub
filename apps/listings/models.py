# apps/listings/models.py
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator
from django.utils.text import slugify
from django.db.models import F
from apps.categories.models import Category


class Listing(models.Model):
    """Main listing model for equipment and services"""

    class Type(models.TextChoices):
        SELL = "sell", _("For Sale")
        RENT = "rent", _("For Rent")
        LEASE = "lease", _("For Lease")
        SERVICE = "service", _("Service")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PUBLISHED = "published", _("Published")
        ARCHIVED = "archived", _("Archived")
        FLAGGED = "flagged", _("Flagged")
        SUSPENDED = "suspended", _("Suspended")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="listings",
        help_text=_("Listing owner"),
    )
    title = models.CharField(max_length=200, help_text=_("Listing title"))
    slug = models.SlugField(max_length=220, unique=True,
                            blank=True, help_text=_("SEO-friendly URL"))
    description = models.TextField(help_text=_(
        "Detailed description of the listing"))
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="listings", help_text=_("Listing category")
    )

    listing_type = models.CharField(
        max_length=10, choices=Type.choices, help_text=_("Type of listing"))
    price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    currency = models.CharField(
        max_length=3, default="NGN", help_text=_("Currency code (NGN for Naira)"))
    price_unit = models.CharField(max_length=30, blank=True)
    negotiable = models.BooleanField(default=False)

    location = models.CharField(max_length=200)
    country = models.CharField(max_length=100, blank=True)
    state_province = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100, blank=True)

    contact_name = models.CharField(max_length=100)
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=30, blank=True)

    manufacturer = models.CharField(max_length=100, blank=True)
    model = models.CharField(max_length=100, blank=True)
    year = models.PositiveIntegerField(null=True, blank=True)
    condition = models.CharField(
        max_length=30,
        choices=[
            ("new", _("New")),
            ("excellent", _("Excellent")),
            ("good", _("Good")),
            ("fair", _("Fair")),
            ("poor", _("Poor")),
        ],
        blank=True,
    )

    service_area = models.CharField(max_length=200, blank=True)

    status = models.CharField(
        max_length=30, choices=Status.choices, default=Status.DRAFT)
    featured = models.BooleanField(default=False)
    views_count = models.PositiveIntegerField(default=0)
    inquiries_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "listings"
        verbose_name = _("Listing")
        verbose_name_plural = _("Listings")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["category", "status"]),
            models.Index(fields=["listing_type", "status"]),
            models.Index(fields=["location"]),
            models.Index(fields=["-published_at"]),
            models.Index(fields=["user", "status"]),
            models.Index(fields=["country", "state_province", "city"]),
        ]

    def __str__(self):
        return self.title

    @property
    def is_published(self):
        return self.status == self.Status.PUBLISHED

    @property
    def is_expired(self):
        if not self.expires_at:
            return False
        from django.utils import timezone

        return timezone.now() > self.expires_at

    @property
    def is_equipment(self):
        return self.listing_type in [self.Type.SELL, self.Type.RENT, self.Type.LEASE]

    @property
    def is_service(self):
        return self.listing_type == self.Type.SERVICE

    @property
    def price_display(self):
        if self.price:
            return f"₦{self.price:,.2f}" + (f" / {self.price_unit}" if self.price_unit else "")
        return "Contact for price"

    def increment_views(self):
        # DB-side increment (atomic-ish). Refresh instance so view_count available.
        Listing.objects.filter(pk=self.pk).update(
            views_count=F("views_count") + 1)
        try:
            self.refresh_from_db(fields=["views_count"])
        except Exception:
            pass

    def increment_inquiries(self):
        Listing.objects.filter(pk=self.pk).update(
            inquiries_count=F("inquiries_count") + 1)
        try:
            self.refresh_from_db(fields=["inquiries_count"])
        except Exception:
            pass

    def expire_if_needed(self):
        if self.is_expired and self.status == self.Status.PUBLISHED:
            self.status = self.Status.ARCHIVED
            self.save(update_fields=["status"])

    def save(self, *args, **kwargs):
        # slug generation
        if not self.slug:
            base_slug = slugify(self.title)
            slug = base_slug
            counter = 1
            while Listing.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug

        # published_at set when published
        if self.status == self.Status.PUBLISHED and not self.published_at:
            from django.utils import timezone

            self.published_at = timezone.now()

        # enforce single featured per user (for now)
        if self.featured:
            Listing.objects.filter(user=self.user, featured=True).exclude(
                pk=self.pk).update(featured=False)

        super().save(*args, **kwargs)


class ListingImage(models.Model):
    listing = models.ForeignKey(
        Listing, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="listings/images/")
    caption = models.CharField(max_length=200, blank=True)
    is_primary = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "listing_images"
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"Image for {self.listing.title}"


class ListingDocument(models.Model):
    listing = models.ForeignKey(
        Listing, on_delete=models.CASCADE, related_name="documents")
    document = models.FileField(upload_to="listings/documents/")
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    file_size = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "listing_documents"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} - {self.listing.title}"

    def save(self, *args, **kwargs):
        # set file_size if missing
        if self.document and not self.file_size:
            try:
                self.file_size = self.document.size
            except Exception:
                pass
        super().save(*args, **kwargs)


class ListingView(models.Model):
    listing = models.ForeignKey(
        Listing, on_delete=models.CASCADE, related_name="view_records")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                             null=True, blank=True, related_name="listing_views")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "listing_views"
        ordering = ["-viewed_at"]
        indexes = [models.Index(fields=["listing", "-viewed_at"]),
                   models.Index(fields=["-viewed_at"])]

    def __str__(self):
        return f"View of {self.listing.title} at {self.viewed_at}"
