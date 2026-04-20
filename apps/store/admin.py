from django.contrib import admin

from .models import Store

# Register your models here.


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'slug', 'name', 'description', 'banner_image', 'logo',
                    'policy', 'is_active', 'is_published', 'created_at', 'updated_at')
    list_filter = ('is_active', 'is_published', 'created_at', 'updated_at')
    search_fields = ('user__email', 'name', 'description', 'categories__name')
    readonly_fields = ('created_at', 'updated_at')
    fields = ('user', 'slug', 'categories', 'name', 'description', 'banner_image',
              'logo', 'email', 'phone', 'address', 'city', 'state', 'country', 'zip_code', 'policy', 'is_active', 'is_published')
    list_display_links = ('name',)
    list_editable = ('is_active', 'is_published')
    list_per_page = 20
    ordering = ('-created_at',)
    date_hierarchy = 'created_at'

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('categories')
