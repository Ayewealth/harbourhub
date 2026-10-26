import pytest

from tests.factories import OrderFactory


@pytest.mark.django_db
def test_factories_create_a_consistent_order():
    order = OrderFactory()

    assert order.pk is not None
    assert order.store_id is not None
    assert order.seller_id == order.store.user_id
    assert order.currency == "NGN"


@pytest.mark.django_db
def test_celery_runs_eagerly(settings):
    assert settings.CELERY_TASK_ALWAYS_EAGER is True
