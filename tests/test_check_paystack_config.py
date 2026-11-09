import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


@pytest.mark.django_db
def test_rejects_test_keys(settings):
    settings.PAYSTACK_SECRET_KEY = "sk_test_x"
    settings.PAYSTACK_PUBLIC_KEY = "pk_test_x"
    settings.PAYSTACK_WEBHOOK_URL = (
        "https://api.harbourhubglobal.com/commerce/webhooks/paystack/"
    )

    with pytest.raises(CommandError):
        call_command("check_paystack_config")


@pytest.mark.django_db
def test_accepts_live_prefixes_without_sending(settings):
    settings.PAYSTACK_SECRET_KEY = "sk_live_x"
    settings.PAYSTACK_PUBLIC_KEY = "pk_live_x"
    settings.PAYSTACK_WEBHOOK_URL = (
        "https://api.harbourhubglobal.com/commerce/webhooks/paystack/"
    )

    call_command("check_paystack_config")
