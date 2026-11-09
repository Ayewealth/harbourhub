from django.contrib import admin

from .models import (
    BankAccount,
    Payout,
    PayoutAllocation,
    VendorEarning,
    VendorWallet,
    WalletTransaction,
)


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "bank_name", "account_name",
                    "masked_account_number", "is_default", "is_verified")
    list_filter = ("is_default", "is_verified", "bank_name")
    search_fields = ("user__email", "account_name", "bank_name")
    exclude = ("account_number",)

    @admin.display(description="Account number")
    def masked_account_number(self, obj):
        number = obj.account_number or ""
        return f"****{number[-4:]}" if number else ""


@admin.register(VendorEarning)
class VendorEarningAdmin(admin.ModelAdmin):
    list_display = ("id", "vendor", "store", "order", "earning_type",
                    "status", "net_amount", "currency", "created_at")
    list_filter = ("status", "earning_type", "currency")
    search_fields = ("vendor__email", "order__order_number")
    ordering = ("-created_at",)


@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = ("id", "vendor", "store", "amount", "currency", "status",
                    "created_at")
    list_filter = ("status", "currency")
    search_fields = ("vendor__email", "reference")
    ordering = ("-created_at",)


@admin.register(VendorWallet)
class VendorWalletAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "store", "pending_balance",
                    "available_balance", "total_withdrawn", "currency")
    search_fields = ("user__email", "store__name")


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ("id", "wallet", "transaction_type", "amount",
                    "created_at")
    list_filter = ("transaction_type",)
    search_fields = ("wallet__user__email", "description")
    ordering = ("-created_at",)


@admin.register(PayoutAllocation)
class PayoutAllocationAdmin(admin.ModelAdmin):
    list_display = ("id", "payout", "earning", "amount", "created_at")
    search_fields = ("payout__reference",)
    ordering = ("-created_at",)
