# apps/listings/admin.py
from django.contrib import admin
from .models import Listing, ListingImage, ListingDocument, ListingView


class ListingImageInline(admin.TabularInline):
    model = ListingImage
    extra = 0
    readonly_fields = ("created_at",)
    fields = ("image", "caption", "is_primary", "sort_order")


class ListingDocumentInline(admin.TabularInline):
    model = ListingDocument
    extra = 0
    readonly_fields = ("file_size", "created_at")
    fields = ("name", "document", "description", "file_size")


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "user", "status",
                    "featured", "price", "currency", "created_at")
    list_filter = ("status", "featured", "listing_type", "category", "user")
    search_fields = ("title", "description", "contact_email",
                     "user__email", "user__username")
    readonly_fields = ("views_count", "inquiries_count",
                       "published_at", "created_at", "updated_at")
    inlines = (ListingImageInline, ListingDocumentInline)
    actions = ("mark_published", "mark_archived", "toggle_featured")

    def mark_published(self, request, queryset):
        updated = queryset.update(status=Listing.Status.PUBLISHED)
        self.message_user(request, f"{updated} listing(s) marked published.")
    mark_published.short_description = "Mark selected as published"

    def mark_archived(self, request, queryset):
        updated = queryset.update(status=Listing.Status.ARCHIVED)
        self.message_user(request, f"{updated} listing(s) archived.")
    mark_archived.short_description = "Archive selected listings"

    def toggle_featured(self, request, queryset):
        """For admin: toggle featured on selected listing and unset others for same user."""
        for listing in queryset:
            if not listing.featured:
                # unset others for owner
                Listing.objects.filter(user=listing.user, featured=True).exclude(
                    pk=listing.pk).update(featured=False)
                listing.featured = True
            else:
                listing.featured = False
            listing.save()
        self.message_user(request, "Toggled featured for selected listings.")
    toggle_featured.short_description = "Toggle featured flag"


@admin.register(ListingImage)
class ListingImageAdmin(admin.ModelAdmin):
    list_display = ("id", "listing", "is_primary", "sort_order", "created_at")
    list_filter = ("is_primary",)
    search_fields = ("listing__title",)


@admin.register(ListingDocument)
class ListingDocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "listing", "name", "file_size", "created_at")
    search_fields = ("name", "listing__title")


@admin.register(ListingView)
class ListingViewAdmin(admin.ModelAdmin):
    list_display = ("id", "listing", "user", "ip_address", "viewed_at")
    search_fields = ("listing__title", "user__email")
    readonly_fields = ("listing", "user", "ip_address",
                       "user_agent", "viewed_at")
