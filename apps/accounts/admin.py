# accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from .models import User
from django.utils.translation import gettext_lazy as _


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    model = User
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
