# accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from .models import (
    DeliveryDetail, OneTimePassword, PasswordResetToken, User, UserPreference,
    UserSession, UserTwoFactor, VerificationRequest,
)
from django.utils.translation import gettext_lazy as _


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    model = User

    readonly_fields = ("created_at", "updated_at")

    ordering = ('-created_at',)
    list_display = ('email', 'username', 'role', 'is_verified',
                    'is_staff', 'is_superuser', 'created_at')
    list_filter = ('role', 'is_verified', 'is_staff', 'is_superuser')
    search_fields = ('email', 'username', 'company', 'phone')

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        (_('Personal info'), {
         'fields': ('username', 'company', 'phone', 'location')}),
        (_('Permissions'), {'fields': ('role', 'is_verified', 'is_active',
         'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        (_('Important dates'), {
         'fields': ('last_login', 'created_at', 'updated_at')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'username', 'password1', 'password2'),
        }),
    )


@admin.register(OneTimePassword)
class OneTimePasswordAdmin(admin.ModelAdmin):
    list_display = ('email', 'code', 'purpose',
                    'expires_at', 'used', 'created_at')


@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "used", "expires_at", "created_at")
    list_filter = ("used",)
    search_fields = ("user__email",)
    readonly_fields = ("user", "token", "created_at", "used", "expires_at")
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(VerificationRequest)
class VerificationRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "company_name", "business_type", "status",
                    "created_at", "reviewed_at")
    list_filter = ("status", "business_type")
    search_fields = ("user__email", "company_name")
    ordering = ("-created_at",)


@admin.register(DeliveryDetail)
class DeliveryDetailAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "contact_person", "city", "state",
                    "country", "is_default", "created_at")
    list_filter = ("is_default", "country")
    search_fields = ("user__email", "contact_person", "address")
    ordering = ("-created_at",)


@admin.register(UserPreference)
class UserPreferenceAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "language", "preferred_currency",
                    "email_newsletter", "email_order_updates", "updated_at")
    list_filter = ("language", "email_newsletter", "email_unsubscribe_all")
    search_fields = ("user__email",)


@admin.register(UserTwoFactor)
class UserTwoFactorAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "is_enabled", "created_at")
    list_filter = ("is_enabled",)
    search_fields = ("user__email",)
    exclude = ("secret",)


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "device_name", "device_type", "is_active",
                    "last_active", "created_at")
    list_filter = ("device_type", "is_active")
    search_fields = ("user__email", "device_name", "ip_address")
    ordering = ("-last_active",)
