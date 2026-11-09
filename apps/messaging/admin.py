from django.contrib import admin

from .models import Conversation, Message


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "buyer", "vendor", "listing", "last_message_at",
                    "created_at")
    search_fields = ("buyer__email", "vendor__email", "listing__title")
    ordering = ("-last_message_at",)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "sender", "message_type", "is_read",
                    "created_at")
    list_filter = ("message_type", "is_read")
    search_fields = ("sender__email", "body")
    ordering = ("-created_at",)
