import django_filters

from .models import Store


class StoreDirectoryFilter(django_filters.FilterSet):
    """Filters for public vendor directory (published stores)."""

    category = django_filters.NumberFilter(method="filter_category")
    country = django_filters.CharFilter(field_name="country", lookup_expr="iexact")
    state = django_filters.CharFilter(field_name="state", lookup_expr="iexact")
    city = django_filters.CharFilter(field_name="city", lookup_expr="iexact")
    date_from = django_filters.DateFilter(
        field_name="created_at", lookup_expr="date__gte"
    )
    date_to = django_filters.DateFilter(
        field_name="created_at", lookup_expr="date__lte"
    )

    class Meta:
        model = Store
        fields = ["category", "country", "state", "city"]

    def filter_category(self, queryset, name, value):
        if value is None:
            return queryset
        return queryset.filter(categories__id=value).distinct()
