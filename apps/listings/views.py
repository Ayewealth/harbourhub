# listings/views.py
from apps.listings.tasks import record_listing_view_task
from .permissions import IsOwnerOrAdminOrReadOnly, CanCreateListing
from .filters import ListingFilter
import logging

from django.db.models import Avg, Count, FloatField, Q, Value
from django.db.models.functions import Coalesce
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from drf_spectacular.utils import extend_schema, extend_schema_view,  OpenApiExample, inline_serializer
from rest_framework import filters, generics, permissions, status, viewsets, serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Listing, ListingView
from .serializers import (
    ListingListSerializer, ListingDetailSerializer,
    ListingCreateUpdateSerializer, MyListingSerializer
)

logger = logging.getLogger(__name__)


@extend_schema_view(
    list=extend_schema(
        summary="List listings",
        description="Get paginated list of published listings with filtering and search"
    ),
    retrieve=extend_schema(
        summary="Get listing details",
        description="Get detailed information about a specific listing"
    ),
    create=extend_schema(
        summary="Create listing",
        description="Create a new listing (sellers and service providers only)"
    ),
    update=extend_schema(
        summary="Update listing",
        description="Update listing (owner only)"
    ),
    destroy=extend_schema(
        summary="Delete listing",
        description="Delete listing (owner or admin only)"
    )
)
class ListingViewSet(viewsets.ModelViewSet):
    """CRUD operations for listings"""

    queryset = Listing.objects.select_related(
        'category', 'user').prefetch_related('images')
    permission_classes = [IsOwnerOrAdminOrReadOnly, CanCreateListing]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ListingFilter
    search_fields = ['title', 'description',
                     'manufacturer', 'model', 'location']
    ordering_fields = ['created_at', 'updated_at',
                       'price', 'views_count', 'published_at']
    ordering = ['-created_at']

    def get_queryset(self):
        """Filter queryset based on action and user"""
        queryset = super().get_queryset()

        if self.action == 'list':
            # Show only published listings for list view
            return queryset.filter(status=Listing.Status.PUBLISHED)
        elif self.action in ['retrieve']:
            # Show published or user's own listings for detail view
            user = self.request.user
            if user and user.is_authenticated:
                return queryset.filter(Q(status=Listing.Status.PUBLISHED) | Q(user=user))
            return queryset.filter(status=Listing.Status.PUBLISHED)

        return queryset

    def get_serializer_class(self):
        """Return appropriate serializer based on action"""
        if self.action == 'list':
            return ListingListSerializer
        elif self.action == 'retrieve':
            return ListingDetailSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return ListingCreateUpdateSerializer
        elif self.action == 'my_listings':
            return MyListingSerializer
        return ListingDetailSerializer

    def retrieve(self, request, *args, **kwargs):
        """
        Get listing details and increment view count (published listings only).
        - We increment synchronously (fast DB F() update) so the client sees the new count
          immediately.
        - We enqueue a Celery task to record the detailed view record (user/ip/ua) for analytics.
        """
        instance = self.get_object()

        if instance.status == Listing.Status.PUBLISHED:
            try:
                # fast DB-side increment (F() update) — safe under concurrency
                instance.increment_views()

                # Enqueue analytics task to create ListingView record (async)
                user_id = request.user.id if request.user.is_authenticated else None
                ip = self.get_client_ip(request)
                ua = request.META.get('HTTP_USER_AGENT', '')
                # record_listing_view_task should *only* create the ListingView analytics row.
                record_listing_view_task.delay(
                    listing_id=instance.pk, user_id=user_id, ip_address=ip, user_agent=ua)
            except Exception as exc:
                logger.exception(
                    "Failed to record/increment listing view for %s: %s", instance.pk, exc)
                # don't stop request — return listing details regardless

            # Refresh instance so .views_count reflects the increment we just made
            try:
                instance.refresh_from_db(fields=['views_count'])
            except Exception:
                # ignore refresh failures (very unlikely)
                pass

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def perform_create(self, serializer):
        """
        Save new listing. If the request attempted to set `featured=True`, we will
        atomically unset any other featured listing for this owner before saving.
        """
        user = self.request.user
        # serializer will get request from self.get_serializer_context automatically in DRF
        # But ensure serializer context includes request (DRF does this). If you ever instantiate serializer manually you MUST pass context={'request': request}.
        validated_data = getattr(serializer, "validated_data", None)
        # Save: serializer.create handles featured flag too, but we also ensure no duplicates
        # call save with user param is supported by serializer.create
        listing = serializer.save(user=user)
        return listing

    def perform_update(self, serializer):
        """
        Update listing. For featured toggles, serializer.update handles unsetting other featured listings.
        """
        instance = serializer.instance
        user = self.request.user

        # Only owner or admin may toggle featured on an existing listing. Serializer enforces this; we keep the operation here.
        updated = serializer.save()
        return updated

    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(
        summary="Get my listings",
        description="Get current user's listings with all statuses"
    )
    @action(detail=False, methods=['get'])
    def my_listings(self, request):
        """Get current user's listings"""
        if not (request.user and request.user.is_authenticated):
            return Response({"detail": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        queryset = self.get_queryset().filter(user=request.user)
        queryset = self.filter_queryset(queryset)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @extend_schema(
        summary="Publish listing",
        description="Publish a draft listing"
    )
    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        """Publish a listing"""
        listing = self.get_object()

        if listing.status != Listing.Status.DRAFT:
            return Response({'error': 'Only draft listings can be published'}, status=status.HTTP_400_BAD_REQUEST)

        # Only owner or admin can publish
        if not (request.user == listing.user or getattr(request.user, "is_admin_user", False)):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        listing.status = Listing.Status.PUBLISHED
        listing.save(update_fields=['status', 'published_at'])

        return Response({'message': 'Listing published successfully'}, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Archive listing",
        description="Archive an active listing"
    )
    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        """Archive a listing"""
        listing = self.get_object()

        # Only owner or admin can archive
        if not (request.user == listing.user or getattr(request.user, "is_admin_user", False)):
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        listing.status = Listing.Status.ARCHIVED
        listing.save(update_fields=['status'])

        return Response({'message': 'Listing archived successfully'}, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Upload Images",
        description="Upload one or more images for a listing.",
        request=inline_serializer(
            name="UploadListingImagesRequest",
            fields={
                "images_data": serializers.ListField(
                    child=serializers.ImageField()
                )
            },
        ),
        responses={200: inline_serializer(
            name="UploadListingImagesResponse",
            fields={
                "message": serializers.CharField()
            },
        )},
        examples=[
            OpenApiExample(
                "Upload images example",
                description="Use multipart/form-data and repeat images_data for multiple files.",
                value={
                    "images_data": ["<file1>", "<file2>"]
                },
                request_only=True,
            ),
        ],
    )
    @action(detail=True, methods=['post'], url_path='upload-images')
    def upload_images(self, request, pk=None):
        listing = self.get_object()
        images = request.FILES.getlist('images_data')
        if not images:
            return Response({'error': 'No images provided'}, status=400)

        start_order = listing.images.count()
        has_primary = listing.images.filter(is_primary=True).exists()
        for i, image in enumerate(images):
            ListingImage.objects.create(
                listing=listing,
                image=image,
                is_primary=(not has_primary and i == 0),
                sort_order=start_order + i,
            )
        return Response({'message': f'{len(images)} image(s) uploaded successfully'})

    @extend_schema(
        summary="Set Primary Image",
        description="Set one existing listing image as the primary image.",
        request=inline_serializer(
            name="SetPrimaryImageRequest",
            fields={
                "image_id": serializers.IntegerField()
            },
        ),
        responses={200: inline_serializer(
            name="SetPrimaryImageResponse",
            fields={
                "message": serializers.CharField()
            },
        )},
        examples=[
            OpenApiExample(
                "Set primary image example",
                value={
                    "image_id": 12
                },
                request_only=True,
            ),
        ],
    )
    @action(detail=True, methods=['post'], url_path='set-primary-image')
    def set_primary_image(self, request, pk=None):
        listing = self.get_object()
        image_id = request.data.get('image_id')

        if not image_id:
            return Response({'error': 'image_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            image = listing.images.get(id=image_id)
        except ListingImage.DoesNotExist:
            return Response({'error': 'Image not found for this listing'}, status=status.HTTP_404_NOT_FOUND)

        # Unset all, then set the chosen one
        listing.images.update(is_primary=False)
        image.is_primary = True
        image.save(update_fields=['is_primary'])

        return Response({'message': f'Image {image_id} set as primary successfully'})

    def get_client_ip(self, request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


@extend_schema_view(
    get=extend_schema(
        summary="Top deals",
        description=(
            "Published listings prioritized by `featured`, then `published_at`, "
            "then `created_at`. Query param `limit` (default 20, max 50)."
        ),
    ),
)
class TopDealsListView(generics.ListAPIView):
    serializer_class = ListingListSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None
    filter_backends = []

    def get_queryset(self):
        try:
            limit = int(self.request.query_params.get("limit", 20))
        except (TypeError, ValueError):
            limit = 20
        limit = min(max(limit, 1), 50)

        return (
            Listing.objects.filter(status=Listing.Status.PUBLISHED)
            .select_related("category", "user", "store")
            .prefetch_related("images")
            .annotate(
                rating_avg=Coalesce(
                    Avg("reviews__rating"),
                    Value(0.0),
                    output_field=FloatField(),
                ),
                review_count=Count("reviews", distinct=True),
            )
            .order_by("-featured", "-published_at", "-created_at")[:limit]
        )


@extend_schema_view(
    get=extend_schema(
        summary="Best reviewed listings",
        description=(
            "Published listings with at least one review, ordered by average rating, "
            "review count, then recency. Query param `limit` (default 20, max 50)."
        ),
    ),
)
class BestReviewedListView(generics.ListAPIView):
    serializer_class = ListingListSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None
    filter_backends = []

    def get_queryset(self):
        try:
            limit = int(self.request.query_params.get("limit", 20))
        except (TypeError, ValueError):
            limit = 20
        limit = min(max(limit, 1), 50)

        return (
            Listing.objects.filter(status=Listing.Status.PUBLISHED)
            .select_related("category", "user", "store")
            .prefetch_related("images")
            .annotate(
                rating_avg=Coalesce(
                    Avg("reviews__rating"),
                    Value(0.0),
                    output_field=FloatField(),
                ),
                review_count=Count("reviews", distinct=True),
            )
            .filter(review_count__gt=0)
            .order_by(
                "-rating_avg",
                "-review_count",
                "-published_at",
                "-created_at",
            )[:limit]
        )
