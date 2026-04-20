from django.db.models import Avg, Count, FloatField, Q, Value
from django.db.models.functions import Coalesce
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import filters, generics, permissions
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView

from apps.listings.models import Listing

from .filters import StoreDirectoryFilter
from .models import Store
from .permissions import CanCreateStore, CanManageStore, IsStoreOwnerOrAdmin
from .serializers import (
    StoreCreateSerializer,
    StoreUpdateSerializer,
    StoreDetailSerializer,
    StoreListSerializer,
)


def annotate_store_review_stats(queryset):
    """Aggregate store ratings for directory cards and detail."""
    return queryset.annotate(
        rating_avg=Coalesce(
            Avg("reviews__rating"),
            Value(0.0),
            output_field=FloatField(),
        ),
        review_count=Count("reviews", distinct=True),
    )


def annotate_store_for_top_vendors(queryset):
    """Adds published listing count for ranking top vendors."""
    return annotate_store_review_stats(queryset).annotate(
        published_listing_count=Count(
            "listings",
            filter=Q(listings__status=Listing.Status.PUBLISHED),
            distinct=True,
        ),
    )


def _public_directory_queryset():
    return annotate_store_review_stats(
        Store.objects.filter(is_active=True, is_published=True)
        .select_related("user")
        .prefetch_related("categories", "listings", "listings__images")
    )


def _store_detail_queryset():
    return annotate_store_review_stats(
        Store.objects.select_related("user").prefetch_related(
            "categories",
            "listings",
            "listings__images",
        )
    )


@extend_schema_view(
    get=extend_schema(
        summary="List published stores (vendor directory)",
        description="Public catalog of active, published stores. Filter by category id, country, state, city.",
    ),
    post=extend_schema(
        summary="Create a store",
        description="Seller only. Creates a store for the authenticated user.",
    ),
)
class StoreListCreateView(generics.ListCreateAPIView):
    """GET /stores/ — directory; POST /stores/ — create."""

    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_class = StoreDirectoryFilter
    search_fields = ["name", "description", "city", "state", "country"]
    ordering_fields = ["created_at", "updated_at",
                       "name", "rating_avg", "review_count"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return _public_directory_queryset()

    def get_permissions(self):
        if self.request.method == "POST":
            return [permissions.IsAuthenticated(), CanCreateStore()]
        return [permissions.AllowAny()]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return StoreCreateSerializer
        return StoreListSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["listing_limit"] = 6
        return context

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


@extend_schema_view(
    get=extend_schema(
        summary="Top vendors",
        description=(
            "Ranked published stores. Ordering: average review rating, review count, "
            "published listing count, then recency. Query param `limit` (default 20, max 50)."
        ),
    ),
)
class TopVendorsListView(generics.ListAPIView):
    """GET /stores/top/ — homepage merchandising."""

    serializer_class = StoreListSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None
    filter_backends = []

    def get_queryset(self):
        try:
            limit = int(self.request.query_params.get("limit", 20))
        except (TypeError, ValueError):
            limit = 20
        limit = min(max(limit, 1), 50)

        qs = annotate_store_for_top_vendors(
            Store.objects.filter(is_active=True, is_published=True)
            .select_related("user")
            .prefetch_related("categories", "listings", "listings__images")
        ).order_by(
            "-rating_avg",
            "-review_count",
            "-published_listing_count",
            "-created_at",
        )
        return qs[:limit]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["listing_limit"] = 6
        return context


@extend_schema_view(
    get=extend_schema(
        summary="Retrieve store (vendor storefront)",
        description="Public read for published stores. Owners and admins may view unpublished or inactive stores.",
    ),
    put=extend_schema(summary="Replace store"),
    patch=extend_schema(summary="Update store"),
    delete=extend_schema(summary="Delete store"),
)
class StoreRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    """GET|PATCH|DELETE /stores/<slug>/."""

    lookup_field = "slug"
    lookup_url_kwarg = "slug"

    def get_queryset(self):
        user = self.request.user
        base = _store_detail_queryset()
        if user.is_authenticated and getattr(user, "is_admin_user", False):
            return base
        if user.is_authenticated:
            return base.filter(
                Q(is_active=True, is_published=True) | Q(user=user)
            )
        return base.filter(is_active=True, is_published=True)

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return StoreUpdateSerializer
        return StoreDetailSerializer

    def get_permissions(self):
        if self.request.method == "GET":
            return [permissions.AllowAny()]
        return [
            permissions.IsAuthenticated(),
            CanManageStore(),
            IsStoreOwnerOrAdmin(),
        ]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["listing_limit"] = 12
        return context


class StorePublishView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanManageStore]

    def patch(self, request, slug):
        store = get_object_or_404(Store, slug=slug, user=request.user)

        if store.is_published:
            return Response(
                {"error": "Store is already published"},
                status=status.HTTP_400_BAD_REQUEST
            )

        store.is_published = True
        store.save(update_fields=['is_published'])
        return Response({'message': 'Store published successfully'}, status=status.HTTP_200_OK)


class StoreUnpublishView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanManageStore]

    def patch(self, request, slug):
        store = get_object_or_404(Store, slug=slug, user=request.user)

        if not store.is_published:
            return Response(
                {"error": "Store is already unpublished"},
                status=status.HTTP_400_BAD_REQUEST
            )

        store.is_published = False
        store.save(update_fields=["is_published"])

        return Response(
            {"message": "Store unpublished successfully"},
            status=status.HTTP_200_OK
        )
