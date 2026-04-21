# harbour_hub/urls.py
from django.urls import path, include

urlpatterns = [
    # Authentication
    path('auth/', include('apps.accounts.urls')),

    # Core functionality
    path('categories/', include('apps.categories.urls')),
    path('listings/', include('apps.listings.urls')),
    path('inquiries/', include('apps.inquiries.urls')),
    path('stores/', include('apps.store.urls')),
    path('reviews/', include('apps.reviews.urls')),
    path('commerce/', include('apps.commerce.urls')),
    path('financials/', include('apps.financials.urls')),

    # # Admin panel
    path('admin-panel/', include('apps.admin_panel.urls')),
    path('analytics/', include('apps.analytics.urls')),

    # Global Search
    path('search/', include('apps.core.urls'))
]
