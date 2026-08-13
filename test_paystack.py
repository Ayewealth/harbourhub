import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hb.settings')
django.setup()

from apps.commerce.paystack import initialize_transaction
from django.conf import settings

print(f"Key loaded: {'Yes' if settings.PAYSTACK_SECRET_KEY else 'No'}")
print(f"Key starts with sk_: {settings.PAYSTACK_SECRET_KEY.startswith('sk_')}")

data = initialize_transaction(
    email="test@example.com",
    amount_kobo=500000,
    reference="TEST-REF-1234",
    callback_url=settings.PAYSTACK_CALLBACK_URL
)

print(f"Paystack Response: {data}")
