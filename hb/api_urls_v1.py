# harbour_hub/urls.py
from django.urls import path, include
from apps.commerce.views import BuyerSentQuotesView, SellerReceivedQuotesView

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
    path('notifications/', include('apps.notifications.urls')),
    path('messages/', include('apps.messaging.urls')),
    path('compliance/', include('apps.compliance.urls')),
    path('support/', include('apps.support.urls')),

    # # Admin panel
    path('admin-panel/', include('apps.admin_panel.urls')),
    path('analytics/', include('apps.analytics.urls')),

    # Global Search
    path('search/', include('apps.core.urls')),

    # Public Careers / Job Openings
    path('careers/', include('apps.admin_panel.public_careers_urls')),

    # Quote Endpoints
    path('quotes/sent/', BuyerSentQuotesView.as_view(), name='api-quotes-sent'),
    path('quotes/received/', SellerReceivedQuotesView.as_view(), name='api-quotes-received'),
]
