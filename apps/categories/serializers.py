from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from .models import Category


class CategoryListSerializer(serializers.ModelSerializer):
    """Simplified category serializer for lists"""

    listing_count = serializers.SerializerMethodField()
    has_children = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = (
            'id', 'name', 'slug', 'icon', 'parent',
            'listing_count', 'has_children'
        )

    @extend_schema_field(serializers.IntegerField())
    def get_listing_count(self, obj):
        """Get listing count for category"""
        return obj.get_listing_count()

    @extend_schema_field(serializers.BooleanField())
    def get_has_children(self, obj):
        return obj.has_children


class CategorySerializer(serializers.ModelSerializer):
    """Detailed category serializer"""

    children = serializers.SerializerMethodField()
    listing_count = serializers.SerializerMethodField()
    full_name = serializers.CharField(source='get_full_name', read_only=True)

    # ✅ parent is write-only, parent_detail returned instead
    parent = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(),
        required=False,
        allow_null=True,
        write_only=True
    )
    parent_detail = CategoryListSerializer(source="parent", read_only=True)

    class Meta:
        model = Category
        fields = (
            'id', 'name', 'slug', 'description', 'icon',
            'parent', 'parent_detail', 'is_active', 'sort_order',
            'full_name', 'listing_count', 'children',
            'created_at', 'updated_at'
        )

    @extend_schema_field(CategoryListSerializer(many=True))
    def get_children(self, obj):
        """Get child categories (1 level deep, optimized with prefetch)"""
        children = [c for c in obj.children.all() if c.is_active]
        return CategoryListSerializer(
            children, many=True, context=self.context
        ).data

    @extend_schema_field(serializers.IntegerField())
    def get_listing_count(self, obj):
        """Get listing count for category"""
        return obj.get_listing_count()


class CategoryTreeSerializer(serializers.ModelSerializer):
    """Recursive serializer for full nested category tree"""

    children = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ("id", "name", "slug", "icon", "children")

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_children(self, obj):
        """Recursively fetch children"""
        if obj.children.exists():
            return CategoryTreeSerializer(
                obj.children.filter(is_active=True),
                many=True,
                context=self.context
            ).data
        return []


class CategoryCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating categories (admin use)"""

    icon = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = Category
        fields = (
            'name', 'description', 'icon', 'parent',
            'is_active', 'sort_order'
        )

    def validate_parent(self, value):
        """Validate parent category"""
        if value and self.instance and value == self.instance:
            raise serializers.ValidationError(
                "Category cannot be its own parent.")

        # Prevent circular reference
        if value and self.instance:
            ancestors = value.get_ancestors(include_self=True)
            if self.instance in ancestors:
                raise serializers.ValidationError(
                    "This would create a circular reference.")

        return value

    def validate_name(self, value):
        """Validate category name uniqueness (case-insensitive)"""
        value = value.strip()
        queryset = Category.objects.filter(name__iexact=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(
                "Category with this name already exists.")

        return value
