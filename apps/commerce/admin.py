from django.contrib import admin

from .models import (
    Cart,
    CartItem,
    CheckoutSession,
    Dispute,
    Order,
    OrderActivity,
    OrderItem,
    Payment,
    QuoteRequest,
    Refund,
    RentalExtension,
    WebhookEvent,
)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "order_number", "buyer", "seller", "status",
                    "total_amount", "currency", "created_at")
    list_filter = ("status", "currency", "created_at")
    search_fields = ("order_number", "buyer__email", "seller__email")
    readonly_fields = ("order_number", "created_at", "updated_at")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "listing", "purchase_type", "quantity",
                    "unit_price")
    list_filter = ("purchase_type",)
    search_fields = ("order__order_number",)


@admin.register(OrderActivity)
class OrderActivityAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "event_type", "created_at")
    list_filter = ("event_type",)
    search_fields = ("order__order_number",)
    readonly_fields = ("order", "event_type", "message", "created_at")
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(CheckoutSession)
class CheckoutSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "buyer", "total_amount", "currency", "created_at")
    list_filter = ("currency",)
    search_fields = ("buyer__email",)
    ordering = ("-created_at",)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "reference", "buyer", "amount", "status",
                    "created_at")
    list_filter = ("status", "currency")
    search_fields = ("reference", "buyer__email")
    ordering = ("-created_at",)


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ("id", "buyer", "created_at")
    search_fields = ("buyer__email",)
    ordering = ("-created_at",)


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ("id", "cart", "listing", "quantity", "unit_price")
    list_filter = ("purchase_type",)
    search_fields = ("listing__title",)


@admin.register(QuoteRequest)
class QuoteRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "listing", "buyer", "store", "status",
                    "created_at")
    list_filter = ("status",)
    search_fields = ("listing__title", "buyer__email")
    ordering = ("-created_at",)


@admin.register(RentalExtension)
class RentalExtensionAdmin(admin.ModelAdmin):
    list_display = ("id", "order_item", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("order_item__order__order_number",)
    ordering = ("-created_at",)


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ("id", "event_type", "gateway_event_id", "status",
                    "created_at")
    list_filter = ("status", "provider")
    search_fields = ("gateway_event_id", "event_type")
    readonly_fields = (
        "provider", "event_type", "gateway_event_id", "status",
        "payload", "created_at",
    )
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = ("id", "reference", "payment", "amount", "status",
                    "created_at")
    list_filter = ("status",)
    search_fields = ("reference", "payment__reference")
    ordering = ("-created_at",)


@admin.register(Dispute)
class DisputeAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "buyer", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("order__order_number", "buyer__email")
    ordering = ("-created_at",)
