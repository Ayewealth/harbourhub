from django.contrib import admin

from .models import ListingReview, StoreReview


@admin.register(ListingReview)
class ListingReviewAdmin(admin.ModelAdmin):
    list_display = ("id", "listing", "reviewer", "rating", "created_at")
    list_filter = ("rating",)
    search_fields = ("comment", "listing__title")


@admin.register(StoreReview)
class StoreReviewAdmin(admin.ModelAdmin):
    list_display = ("id", "store", "reviewer", "rating", "created_at")
    list_filter = ("rating",)
    search_fields = ("comment", "store__name")
