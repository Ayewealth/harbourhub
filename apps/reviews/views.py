from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import generics, permissions

from .models import ListingReview, StoreReview
from .serializers import (
    ListingReviewCreateSerializer,
    ListingReviewSerializer,
    StoreReviewCreateSerializer,
    StoreReviewSerializer,
)


@extend_schema_view(
    get=extend_schema(
        summary="List listing reviews",
        description="Filter with query param `listing` (listing id).",
    ),
    post=extend_schema(summary="Create listing review"),
)
class ListingReviewListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        qs = ListingReview.objects.select_related(
            "reviewer", "listing"
        ).order_by("-created_at")
        listing_id = self.request.query_params.get("listing")
        if listing_id:
            qs = qs.filter(listing_id=listing_id)
        return qs

    def get_serializer_class(self):
        if self.request.method == "POST":
            return ListingReviewCreateSerializer
        return ListingReviewSerializer


@extend_schema_view(
    get=extend_schema(
        summary="List store reviews",
        description="Filter with query param `store` (store id).",
    ),
    post=extend_schema(summary="Create store review"),
)
class StoreReviewListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        qs = StoreReview.objects.select_related(
            "reviewer", "store"
        ).order_by("-created_at")
        store_id = self.request.query_params.get("store")
        if store_id:
            qs = qs.filter(store_id=store_id)
        return qs

    def get_serializer_class(self):
        if self.request.method == "POST":
            return StoreReviewCreateSerializer
        return StoreReviewSerializer
