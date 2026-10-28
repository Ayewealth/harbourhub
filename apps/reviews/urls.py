from django.urls import path

from .views import (
    ListingReviewDetailView,
    ListingReviewListCreateView,
    StoreReviewDetailView,
    StoreReviewListCreateView,
)

urlpatterns = [
    path("listings/", ListingReviewListCreateView.as_view(), name="review-listing-list-create"),
    path("listings/<int:pk>/", ListingReviewDetailView.as_view(), name="review-listing-detail"),
    path("stores/", StoreReviewListCreateView.as_view(), name="review-store-list-create"),
    path("stores/<int:pk>/", StoreReviewDetailView.as_view(), name="review-store-detail"),
]
