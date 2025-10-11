# harbour_hub/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),

    # API v1
    path('api/v1/', include([
        # Authentication
        path('auth/', include('apps.accounts.urls')),

        # Core functionality
        path('categories/', include('apps.categories.urls')),
        path('listings/', include('apps.listings.urls')),
        path('inquiries/', include('apps.inquiries.urls')),

        # # Admin panel
        path('admin-panel/', include('apps.admin_panel.urls')),
        path('analytics/', include('apps.analytics.urls')),
        
        # Global Search
        path('search/', include('apps.core.urls'))
    ])),

    # API Documentation
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'),
         name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL,
                          document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL,
                          document_root=settings.STATIC_ROOT)
