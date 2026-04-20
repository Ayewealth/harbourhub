from django.urls import path

from .views import ListingReviewListCreateView, StoreReviewListCreateView

urlpatterns = [
    path("listings/", ListingReviewListCreateView.as_view(), name="review-listing-list-create"),
    path("stores/", StoreReviewListCreateView.as_view(), name="review-store-list-create"),
]
