import django_filters
from django.db.models import Q

from .models import Order, QuoteRequest


class QuoteRequestFilter(django_filters.FilterSet):
    status = django_filters.CharFilter(
        field_name="status", lookup_expr="iexact")
    listing = django_filters.NumberFilter(field_name="listing_id")
    store = django_filters.NumberFilter(field_name="store_id")
    date_from = django_filters.DateFilter(method="filter_date_from")
    date_to = django_filters.DateFilter(method="filter_date_to")

    class Meta:
        model = QuoteRequest
        fields = ["status", "listing", "store"]

    def filter_date_from(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(created_at__date__gte=value)

    def filter_date_to(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(created_at__date__lte=value)


class OrderFilter(django_filters.FilterSet):
    status = django_filters.CharFilter(
        field_name="status", lookup_expr="iexact")
    order_type = django_filters.CharFilter(
        field_name="order_type", lookup_expr="iexact")
    buyer = django_filters.NumberFilter(field_name="buyer_id")
    seller = django_filters.NumberFilter(field_name="seller_id")
    date_from = django_filters.DateFilter(method="filter_date_from")
    date_to = django_filters.DateFilter(method="filter_date_to")

    class Meta:
        model = Order
        fields = ["status", "order_type", "buyer", "seller"]

    def filter_date_from(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(placed_at__date__gte=value)
            | Q(placed_at__isnull=True, created_at__date__gte=value)
        )

    def filter_date_to(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(placed_at__date__lte=value)
            | Q(placed_at__isnull=True, created_at__date__lte=value)
        )
