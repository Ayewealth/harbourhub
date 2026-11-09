from django.contrib import admin

from .models import ComplianceDocument


@admin.register(ComplianceDocument)
class ComplianceDocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "document_type", "party", "status",
                    "is_verified", "created_at")
    list_filter = ("document_type", "status", "is_verified")
    search_fields = ("name", "party__email")
    ordering = ("-created_at",)
