from django.urls import path

from .views import (
    MarketplaceBreakdownView,
    MoveQuoteToCartView,
    OrderListCreateView,
    OrderMarkShippedView,
    QuoteRequestDetailView,
    QuoteRequestListCreateView,
    QuoteRequestActionView,
    OrderDetailView, OrderExtendRentalView, OrderActivityListView, CartView,
    CartItemView,
    CheckoutView,
    PaymentVerifyView,
    QuoteRequestVendorUpdateView,
)
from .webhooks import PaystackWebhookView

urlpatterns = [
    path("quotes/", QuoteRequestListCreateView.as_view(), name="quote-list-create"),
    path("quotes/<int:pk>/", QuoteRequestDetailView.as_view(), name="quote-detail"),
    path("quotes/<int:pk>/<str:action>/",
         QuoteRequestActionView.as_view(), name="quote-action"),
    path("quotes/<int:pk>/move-to-cart/",
         MoveQuoteToCartView.as_view(), name="quote-move-to-cart"),
    path("quotes/<int:pk>/vendor-update/",
         QuoteRequestVendorUpdateView.as_view()),

    # Orders
    path("orders/", OrderListCreateView.as_view(), name="order-list-create"),
    path("orders/<int:pk>/", OrderDetailView.as_view(), name="order-detail"),
    path("orders/<int:pk>/cancel/", OrderDetailView.as_view(), name="order-cancel"),
    path("orders/<int:pk>/extend-rental/",
         OrderExtendRentalView.as_view(), name="order-extend-rental"),
    path("orders/<int:pk>/activity/",
         OrderActivityListView.as_view(), name="order-activity"),
    path("orders/<int:pk>/ship/", OrderMarkShippedView.as_view(),
         name="mark-order-as-shipped"),

    # Cart
    path("cart/", CartView.as_view(), name="cart"),
    path("cart/items/", CartItemView.as_view(), name="cart-item-add"),
    path("cart/items/<int:item_id>/",
         CartItemView.as_view(), name="cart-item-detail"),

    # Checkout & Payment
    path("checkout/", CheckoutView.as_view(), name="checkout"),
    path("payment/verify/<str:reference>/",
         PaymentVerifyView.as_view(), name="payment-verify"),
    path("payment/webhook/",
         PaystackWebhookView.as_view(), name="paystack-webhook"),

    # Admin
    path(
        "admin/marketplace-breakdown/",
        MarketplaceBreakdownView.as_view(),
        name="marketplace-breakdown",
    ),
]
