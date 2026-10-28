import pytest
from django.urls import reverse

from apps.accounts.models import User

from .factories import UserFactory


@pytest.mark.django_db
def test_analytics_overview_is_repeatable(auth_client):
    staff = UserFactory(role=User.Role.ADMIN, is_staff=True)
    client = auth_client(staff)
    url = reverse("analytics-list")

    first = client.get(url)
    second = client.get(url)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.data["generated_at"] == second.data["generated_at"]
