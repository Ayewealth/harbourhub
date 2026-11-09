from django.contrib import admin

from .models import (
    Notification, NotificationDelivery, NotificationPreference,
    PushSubscription,
)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "recipient", "notification_type", "title",
                    "is_read", "created_at")
    list_filter = ("notification_type", "is_read", "priority")
    search_fields = ("recipient__email", "title", "message")
    readonly_fields = ("created_at", "read_at")
    ordering = ("-created_at",)


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "category", "in_app", "email", "sms", "push")
    list_filter = ("category",)
    search_fields = ("user__email",)


@admin.register(NotificationDelivery)
class NotificationDeliveryAdmin(admin.ModelAdmin):
    list_display = ("id", "channel", "status", "recipient", "event_key",
                    "attempts", "created_at")
    list_filter = ("channel", "status")
    search_fields = ("recipient__email", "event_key", "error")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "endpoint", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("user__email", "endpoint")
    readonly_fields = ("created_at", "updated_at")
