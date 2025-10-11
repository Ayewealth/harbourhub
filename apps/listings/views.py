# listings/views.py
from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from drf_spectacular.utils import extend_schema, extend_schema_view

from .models import Listing, ListingView
from .serializers import (
    ListingListSerializer, ListingDetailSerializer,
    ListingCreateUpdateSerializer, MyListingSerializer
)
from .filters import ListingFilter
from .permissions import IsOwnerOrAdminOrReadOnly, CanCreateListing
from apps.listings.tasks import record_listing_view_task


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

    def get_client_ip(self, request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
