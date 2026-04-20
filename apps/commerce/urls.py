from django.urls import path

from .views import (
    MarketplaceBreakdownView,
    OrderListCreateView,
    QuoteRequestDetailView,
    QuoteRequestListCreateView,
    QuoteRequestActionView,
    OrderDetailView
)

urlpatterns = [
    path("quotes/", QuoteRequestListCreateView.as_view(), name="quote-list-create"),
    path("quotes/<int:pk>/", QuoteRequestDetailView.as_view(), name="quote-detail"),
    path("quotes/<int:pk>/<str:action>/",
         QuoteRequestActionView.as_view(), name="quote-action"),
    path("orders/", OrderListCreateView.as_view(), name="order-list-create"),
    path("orders/<int:pk>/", OrderDetailView.as_view(), name="order-detail"),
    path("orders/<int:pk>/cancel/", OrderDetailView.as_view(), name="order-cancel"),
    path(
        "admin/marketplace-breakdown/",
        MarketplaceBreakdownView.as_view(),
        name="marketplace-breakdown",
    ),
]
