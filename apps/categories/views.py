from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, extend_schema_view

from .models import Category
from .serializers import (
    CategorySerializer, CategoryListSerializer,
    CategoryTreeSerializer, CategoryCreateUpdateSerializer
)


@extend_schema_view(
    list=extend_schema(
        summary="List categories",
        description="Get flat list of active categories (non-hierarchical)"
    ),
    retrieve=extend_schema(
        summary="Get category details",
        description="Get detailed information about a specific category"
    )
)
class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only category operations"""

    queryset = Category.objects.filter(is_active=True).prefetch_related(
        "children"
    ).order_by("sort_order", "name")
    serializer_class = CategorySerializer
    permission_classes = [permissions.AllowAny]

    def get_serializer_class(self):
        if self.action == "list":
            return CategoryListSerializer  # flat list
        return CategorySerializer

    @extend_schema(
        summary="Get category tree",
        description="Get complete category hierarchy as nested tree structure"
    )
    @action(detail=False, methods=["get"], serializer_class=CategoryTreeSerializer)
    def tree(self, request):
        """Get category tree structure (recursive)"""
        categories = self.get_queryset().filter(parent=None)  # top-level only
        serializer = self.get_serializer(categories, many=True)
        return Response(serializer.data)


class CategoryAdminViewSet(viewsets.ModelViewSet):
    """Admin CRUD operations for categories"""

    queryset = Category.objects.all().prefetch_related("children")
    serializer_class = CategoryCreateUpdateSerializer
    permission_classes = [permissions.IsAdminUser]
