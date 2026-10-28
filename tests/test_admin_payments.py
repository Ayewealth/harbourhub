from decimal import Decimal

import pytest

from .factories import PaymentFactory, UserFactory, VendorEarningFactory


def _super_admin():
    # is_superuser short-circuits the dashboard module matrix.
    return UserFactory(role="admin", is_staff=True, is_superuser=True)


@pytest.mark.django_db
def test_admin_payment_list_loads(auth_client):
    PaymentFactory(status="success", amount=Decimal("1000.00"))
    client = auth_client(_super_admin())

    response = client.get("/admin-panel/payments/")

    assert response.status_code == 200


@pytest.mark.django_db
def test_admin_payment_list_search_loads(auth_client):
    PaymentFactory(status="success")
    client = auth_client(_super_admin())

    response = client.get("/admin-panel/payments/", {"search": "PAY-TEST"})

    assert response.status_code == 200


@pytest.mark.django_db
def test_admin_payment_stats_use_commission(auth_client):
    earning = VendorEarningFactory(
        gross_amount=Decimal("1000.00"), commission_rate=Decimal("5.00")
    )
    client = auth_client(_super_admin())

    response = client.get("/admin-panel/payments/stats/")

    assert response.status_code == 200
    assert Decimal(str(response.data["platform_revenue"]["value"])) == (
        earning.commission_amount
    )
