from django.contrib import admin

from .models import Feedback, UserSearch

# Register your models here.

admin.site.register(UserSearch)


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ("id", "topic", "feedback", "user", "created_at")
    list_filter = ("feedback",)
    search_fields = ("topic", "user__email")
    ordering = ("-created_at",)
