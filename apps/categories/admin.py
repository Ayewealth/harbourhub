from django.contrib import admin
from mptt.admin import DraggableMPTTAdmin
from .models import Category


@admin.register(Category)
class CategoryAdmin(DraggableMPTTAdmin):
    """
    Admin for hierarchical categories using django-mptt DraggableMPTTAdmin.
    Provides drag-and-drop tree management with useful list filters.
    """
    mptt_indent_field = "name"
    list_display = (
        "tree_actions",
        "indented_title",
        "slug",
        "parent",
        "is_active",
        "sort_order",
        "listing_count",
        "created_at",
        "updated_at",
    )
    list_display_links = ("indented_title",)
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("sort_order", "name")

    def listing_count(self, obj):
        return obj.listings.count()
    listing_count.short_description = "Listings"
