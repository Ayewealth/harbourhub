import django_filters

from .models import Store


class StoreDirectoryFilter(django_filters.FilterSet):
    """Filters for public vendor directory (published stores)."""

    category = django_filters.NumberFilter(method="filter_category")
    country = django_filters.CharFilter(field_name="country", lookup_expr="iexact")
    state = django_filters.CharFilter(field_name="state", lookup_expr="iexact")
    city = django_filters.CharFilter(field_name="city", lookup_expr="iexact")
    verified = django_filters.BooleanFilter(field_name="is_verified")
    location = django_filters.CharFilter(method="filter_location")
    min_rating = django_filters.NumberFilter(method="filter_min_rating")
    max_rating = django_filters.NumberFilter(method="filter_max_rating")
    
    date_from = django_filters.DateFilter(
        field_name="created_at", lookup_expr="date__gte"
    )
    date_to = django_filters.DateFilter(
        field_name="created_at", lookup_expr="date__lte"
    )

    class Meta:
        model = Store
        fields = ["category", "country", "state", "city", "verified", "location", "min_rating", "max_rating"]

    def filter_category(self, queryset, name, value):
        if value is None:
            return queryset
        try:
            from apps.categories.models import Category
            cat = Category.objects.get(pk=int(value))
            descendant_ids = list(cat.get_descendants(
                include_self=True).values_list("pk", flat=True))
            from apps.listings.models import Listing
            return queryset.filter(
                listings__category_id__in=descendant_ids,
                listings__status=Listing.Status.PUBLISHED
            ).distinct()
        except Exception:
            return queryset.distinct()

    def filter_location(self, queryset, name, value):
        if not value:
            return queryset
        from django.db.models import Q
        return queryset.filter(
            Q(city__icontains=value) |
            Q(state__icontains=value) |
            Q(country__icontains=value) |
            Q(address__icontains=value)
        ).distinct()

    def filter_min_rating(self, queryset, name, value):
        from django.db.models import Avg, FloatField, Value
        from django.db.models.functions import Coalesce
        queryset = queryset.annotate(
            rating_avg_filter=Coalesce(
                Avg("reviews__rating"),
                Value(0.0),
                output_field=FloatField(),
            )
        )
        return queryset.filter(rating_avg_filter__gte=value)

    def filter_max_rating(self, queryset, name, value):
        from django.db.models import Avg, FloatField, Value
        from django.db.models.functions import Coalesce
        queryset = queryset.annotate(
            rating_avg_filter=Coalesce(
                Avg("reviews__rating"),
                Value(0.0),
                output_field=FloatField(),
            )
        )
        return queryset.filter(rating_avg_filter__lte=value)
