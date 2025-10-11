# listings/filters.py
import django_filters
from django.db.models import Q
from django_filters import rest_framework as filters
from .models import Listing
from datetime import datetime


class ListingFilter(filters.FilterSet):
    # Price
    price_min = filters.NumberFilter(field_name="price", lookup_expr="gte")
    price_max = filters.NumberFilter(field_name="price", lookup_expr="lte")
    price_range = filters.RangeFilter(field_name="price")

    # Year
    year_min = filters.NumberFilter(field_name="year", lookup_expr="gte")
    year_max = filters.NumberFilter(field_name="year", lookup_expr="lte")
    year_range = filters.RangeFilter(field_name="year")

    # Category (accept id)
    category = filters.NumberFilter(method="filter_category")
    category_slug = filters.CharFilter(method="filter_category_by_slug")

    # Exact filters
    listing_type = filters.CharFilter(
        field_name="listing_type", lookup_expr="iexact")
    status = filters.CharFilter(field_name="status", lookup_expr="iexact")
    featured = filters.BooleanFilter(field_name="featured")

    # Owner filters
    owner_id = filters.NumberFilter(field_name="user__id")
    owner_email = filters.CharFilter(
        field_name="user__email", lookup_expr="iexact")

    # Location
    location = filters.CharFilter(
        field_name="location", lookup_expr="icontains")
    city = filters.CharFilter(field_name="city", lookup_expr="icontains")
    country = filters.CharFilter(field_name="country", lookup_expr="icontains")

    # Currency
    currency = filters.CharFilter(field_name="currency", lookup_expr="iexact")

    # created / published
    created_after = filters.DateFilter(
        field_name="created_at", lookup_expr="gte")
    created_before = filters.DateFilter(
        field_name="created_at", lookup_expr="lte")
    published_after = filters.DateFilter(
        field_name="published_at", lookup_expr="gte")
    published_before = filters.DateFilter(
        field_name="published_at", lookup_expr="lte")

    # Free-text search across several fields
    q = filters.CharFilter(method="filter_search")

    # Ordering (client can request ?ordering=price,-created_at)
    ordering = filters.OrderingFilter(
        fields=(
            ("price", "price"),
            ("created_at", "created_at"),
            ("published_at", "published_at"),
            ("views_count", "views_count"),
            ("inquiries_count", "inquiries_count"),
        )
    )

    class Meta:
        model = Listing
        # default base qs fields — filters are defined above
        fields = []

    def filter_category(self, queryset, name, value):
        """
        Filter by category id and include descendants (MPTT).
        Accepts numeric id.
        """
        try:
            from categories.models import Category
            cat = Category.objects.get(pk=int(value))
            descendant_ids = list(cat.get_descendants(
                include_self=True).values_list("pk", flat=True))
            return queryset.filter(category_id__in=descendant_ids)
        except Exception:
            return queryset.none()

    def filter_category_by_slug(self, queryset, name, value):
        """
        Filter by category slug and include descendants.
        """
        try:
            from categories.models import Category
            cat = Category.objects.get(slug=value)
            descendant_ids = list(cat.get_descendants(
                include_self=True).values_list("pk", flat=True))
            return queryset.filter(category_id__in=descendant_ids)
        except Exception:
            return queryset.none()

    def filter_search(self, queryset, name, value):
        """
        Full-text-ish search across several fields (title, description, manufacturer, model, location).
        Uses icontains so it's simple and DB-portable.
        """
        if not value:
            return queryset
        v = value.strip()
        return queryset.filter(
            Q(title__icontains=v)
            | Q(description__icontains=v)
            | Q(manufacturer__icontains=v)
            | Q(model__icontains=v)
            | Q(location__icontains=v)
        )
