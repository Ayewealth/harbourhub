from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class ComplianceDocument(models.Model):
    """
    Tracks contracts and certifications linked to orders/vendors.
    """

    class DocumentType(models.TextChoices):
        CONTRACT = 'contract', _('Contract')
        CERTIFICATION = 'certification', _('Certification')
        INSURANCE = 'insurance', _('Insurance')
        LICENSE = 'license', _('License')

    class Status(models.TextChoices):
        ACTIVE = 'active', _('Active')
        EXPIRING = 'expiring', _('Expiring Soon')
        EXPIRED = 'expired', _('Expired')
        REJECTED = 'rejected', _('Rejected')
        INCLUDED = 'included', _('Included')
        PENDING = 'pending', _('Pending Review')

    class Party(models.TextChoices):
        BUYER = 'buyer', _('Buyer')
        VENDOR = 'vendor', _('Vendor')

    document_type = models.CharField(
        max_length=20,
        choices=DocumentType.choices,
        db_index=True
    )
    party = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='compliance_documents'
    )
    party_role = models.CharField(
        max_length=10,
        choices=Party.choices,
        default=Party.VENDOR
    )
    order = models.ForeignKey(
        'commerce.Order',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='compliance_documents'
    )
    listing = models.ForeignKey(
        'listings.Listing',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='compliance_documents'
    )
    name = models.CharField(max_length=255)
    file = models.FileField(
        upload_to='compliance/documents/',
        null=True, blank=True
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    # Admin review
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='reviewed_compliance_docs'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    admin_notes = models.TextField(blank=True)

    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'compliance_documents'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['document_type', '-created_at']),
            models.Index(fields=['end_date']),
        ]

    def __str__(self):
        return f"{self.document_type} - {self.name}"

    @property
    def days_remaining(self):
        if self.end_date:
            from django.utils import timezone
            delta = self.end_date - timezone.now().date()
            return delta.days
        return None

    def update_status_by_expiry(self):
        """Auto-update status based on end_date."""
        days = self.days_remaining
        if days is None:
            return
        if days < 0:
            self.status = self.Status.EXPIRED
        elif days <= 10:
            self.status = self.Status.EXPIRING
        else:
            self.status = self.Status.ACTIVE
        self.save(update_fields=['status'])
