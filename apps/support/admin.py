from django.contrib import admin

from .models import SupportTicket


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ("id", "subject", "raised_by", "raised_by_role", "priority",
                    "status", "created_at")
    list_filter = ("status", "priority", "raised_by_role")
    search_fields = ("subject", "raised_by__email")
    ordering = ("-created_at",)
