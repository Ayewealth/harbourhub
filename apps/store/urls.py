from django.urls import path

from .views import (
    StoreActivityListView,
    StoreChecklistView,
    StoreDashboardMetricsView,
    StoreDashboardTrendView,
    StoreListCreateView,
    StoreRetrieveUpdateDestroyView,
    TopVendorsListView,
    StorePublishView,
    StoreUnpublishView,
    BuyerShippingOptionsView,
    SellerShippingProfileViewSet,
)

urlpatterns = [
    path("", StoreListCreateView.as_view(), name="store-list-create"),
    path("top/", TopVendorsListView.as_view(), name="store-top-vendors"),

    # Shipping profiles
    path("me/shipping/", SellerShippingProfileViewSet.as_view({'get': 'list', 'post': 'create'}), name="seller-shipping-list"),
    path("me/shipping/<int:pk>/", SellerShippingProfileViewSet.as_view({'patch': 'partial_update', 'delete': 'destroy'}), name="seller-shipping-detail"),

    path("<slug:slug>/", StoreRetrieveUpdateDestroyView.as_view(), name="store-detail"),
    path("<slug:slug>/publish/", StorePublishView.as_view(), name="store-publish"),
    path("<slug:slug>/unpublish/",
         StoreUnpublishView.as_view(), name="store-unpublish"),
    path("<slug:slug>/shipping-options/", BuyerShippingOptionsView.as_view(), name="store-shipping-options"),

    path("dashboard/checklist/", StoreChecklistView.as_view()),
    path("dashboard/metrics/", StoreDashboardMetricsView.as_view()),
    path("dashboard/trend/", StoreDashboardTrendView.as_view()),
    path("dashboard/activity/", StoreActivityListView.as_view()),
]
