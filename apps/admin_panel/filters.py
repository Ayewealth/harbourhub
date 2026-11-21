import django_filters
from django.contrib.auth import get_user_model

from apps.financials.models import Payout

User = get_user_model()


class AdminPayoutFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(choices=Payout.Status.choices)
    date_from = django_filters.DateFilter(
        field_name='created_at', lookup_expr='date__gte')
    date_to = django_filters.DateFilter(
        field_name='created_at', lookup_expr='date__lte')
    vendor = django_filters.NumberFilter(field_name='vendor_id')
    store = django_filters.NumberFilter(field_name='store_id')

    class Meta:
        model = Payout
        fields = ['status', 'date_from', 'date_to', 'vendor', 'store']


class AdminUserFilter(django_filters.FilterSet):
    status = django_filters.CharFilter(method='filter_status')

    class Meta:
        model = User
        fields = ['status', 'role', 'is_verified']

    def filter_status(self, queryset, name, value):
        if value == 'active':
            return queryset.filter(is_active=True)
        if value == 'inactive':
            return queryset.filter(is_active=False)
        return queryset
