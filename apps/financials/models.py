from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class BankAccount(models.Model):
    """Vendor bank account for payouts."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='bank_accounts'
    )
    store = models.ForeignKey(
        'store.Store',
        on_delete=models.CASCADE,
        related_name='bank_accounts',
        null=True, blank=True
    )
    account_name = models.CharField(max_length=255)
    account_number = models.CharField(max_length=20)
    bank_name = models.CharField(max_length=255)
    bank_code = models.CharField(
        max_length=20, blank=True,
        help_text="Paystack bank code"
    )
    is_default = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'bank_accounts'
        ordering = ['-is_default', '-created_at']

    def save(self, *args, **kwargs):
        if self.is_default:
            BankAccount.objects.filter(
                user=self.user, is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.account_name} - {self.bank_name}"


class VendorEarning(models.Model):
    """Earnings record per completed order for a vendor."""

    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        AVAILABLE = 'available', _('Available')
        PROCESSING = 'processing', _('Processing Payout')
        PAID_OUT = 'paid_out', _('Paid Out')
        REVERSED = 'reversed', _('Reversed')

    class EarningType(models.TextChoices):
        BUY = 'buy', _('Buy Transaction')
        RENT = 'rent', _('Rent/Hire')
        LEASE = 'lease', _('Lease')

    vendor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='earnings'
    )
    store = models.ForeignKey(
        'store.Store',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='earnings'
    )
    order = models.OneToOneField(
        'commerce.Order',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='earning'
    )
    listing = models.ForeignKey(
        'listings.Listing',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='earnings'
    )
    payout = models.ForeignKey(
        'financials.Payout',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='earnings'
    )
    earning_type = models.CharField(
        max_length=10,
        choices=EarningType.choices
    )
    gross_amount = models.DecimalField(
        max_digits=14, decimal_places=2,
        help_text="Total order amount before commission"
    )
    commission_rate = models.DecimalField(
        max_digits=5, decimal_places=2,
        default=5.00,
        help_text="Platform commission percentage"
    )
    commission_amount = models.DecimalField(
        max_digits=14, decimal_places=2
    )
    net_amount = models.DecimalField(
        max_digits=14, decimal_places=2,
        help_text="Amount vendor receives after commission"
    )
    currency = models.CharField(max_length=3, default='NGN')
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True
    )
    available_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When funds become available for payout"
    )
    is_disputed = models.BooleanField(
        default=False,
        help_text="If true, funds cannot be moved to available or paid out"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'vendor_earnings'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['vendor', '-created_at']),
            models.Index(fields=['status', '-created_at']),
        ]

    def save(self, *args, **kwargs):
        # Auto-calculate commission and net
        if self.gross_amount and self.commission_rate:
            self.commission_amount = (
                self.gross_amount * self.commission_rate / 100
            ).quantize(__import__('decimal').Decimal('0.01'))
            self.net_amount = self.gross_amount - self.commission_amount
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Earning {self.pk} for {self.vendor}"


class Payout(models.Model):
    """Payout request from vendor to their bank account."""

    class Status(models.TextChoices):
        REQUESTED = 'requested', _('Requested')
        PROCESSING = 'processing', _('Processing')
        PAID = 'paid', _('Paid')
        FAILED = 'failed', _('Failed')

    vendor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payouts'
    )
    store = models.ForeignKey(
        'store.Store',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='payouts'
    )
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.SET_NULL,
        null=True,
        related_name='payouts'
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, default='NGN')
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.REQUESTED,
        db_index=True
    )
    reference = models.CharField(
        max_length=100, unique=True, blank=True,
        help_text="Paystack transfer reference"
    )
    failure_reason = models.TextField(blank=True)
    receipt_url = models.URLField(blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payouts'
        ordering = ['-created_at']

    def __str__(self):
        return f"Payout {self.pk} - {self.amount} {self.currency}"


class VendorWallet(models.Model):
    """Internal balance tracking for a vendor."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='wallet'
    )
    store = models.OneToOneField(
        'store.Store',
        on_delete=models.CASCADE,
        related_name='wallet',
        null=True, blank=True
    )
    pending_balance = models.DecimalField(
        max_digits=14, decimal_places=2, default=0)
    available_balance = models.DecimalField(
        max_digits=14, decimal_places=2, default=0)
    total_withdrawn = models.DecimalField(
        max_digits=14, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default='NGN')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'vendor_wallets'

    def __str__(self):
        return f"Wallet for {self.user.email} - Available: {self.available_balance}"


class WalletTransaction(models.Model):
    """Audit log for all wallet movements."""

    class Type(models.TextChoices):
        EARNING = 'earning', _('Earning Credit')
        PAYOUT = 'payout', _('Payout Debit')
        REFUND = 'refund', _('Refund/Reversal')
        ADJUSTMENT = 'adjustment', _('Manual Adjustment')

    wallet = models.ForeignKey(
        VendorWallet,
        on_delete=models.CASCADE,
        related_name='transactions'
    )
    transaction_type = models.CharField(max_length=20, choices=Type.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    description = models.CharField(max_length=255)
    reference_id = models.CharField(
        max_length=100, blank=True, help_text="ID of the related object (Order, Payout, etc.)")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'wallet_transactions'
        ordering = ['-created_at']
