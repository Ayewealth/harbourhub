import django_filters
from django.contrib.auth import get_user_model

User = get_user_model()


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
