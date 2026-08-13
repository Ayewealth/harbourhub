import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hb.settings')
django.setup()

import requests
from django.conf import settings

PAYSTACK_BASE_URL = "https://api.paystack.co"

def _headers():
    return {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }

payload = {
    "email": "test@example.com",
    "amount": 0,
    "reference": "TEST-REF-ZERO-AMOUNT",
    "metadata": {"custom": "field"},
}

response = requests.post(
    f"{PAYSTACK_BASE_URL}/transaction/initialize",
    json=payload,
    headers=_headers(),
    timeout=30
)
print("Status Code:", response.status_code)
print("Response:", response.json())
