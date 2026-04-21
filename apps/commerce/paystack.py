import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

PAYSTACK_BASE_URL = "https://api.paystack.co"


def _headers():
    return {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }


def initialize_transaction(email: str, amount_kobo: int,
                           reference: str, metadata: dict = None,
                           callback_url: str = None) -> dict | None:
    """
    Initialize a Paystack transaction.
    amount_kobo: amount in kobo (NGN * 100)
    Returns data dict or None on failure.
    Docs: https://paystack.com/docs/api/transaction/#initialize
    """
    payload = {
        "email": email,
        "amount": amount_kobo,
        "reference": reference,
        "metadata": metadata or {},
    }
    if callback_url:
        payload["callback_url"] = callback_url

    try:
        response = requests.post(
            f"{PAYSTACK_BASE_URL}/transaction/initialize",
            json=payload,
            headers=_headers(),
            timeout=30
        )
        data = response.json()
        if data.get("status"):
            return data["data"]
        logger.error("Paystack initialize failed: %s", data)
    except Exception as exc:
        logger.exception("Paystack initialize error: %s", exc)
    return None


def verify_transaction(reference: str) -> dict | None:
    """
    Verify a Paystack transaction by reference.
    Docs: https://paystack.com/docs/api/transaction/#verify
    """
    try:
        response = requests.get(
            f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}",
            headers=_headers(),
            timeout=30
        )
        data = response.json()
        if data.get("status"):
            return data["data"]
        logger.error("Paystack verify failed: %s", data)
    except Exception as exc:
        logger.exception("Paystack verify error: %s", exc)
    return None


def create_transfer_recipient(account_name: str, account_number: str,
                              bank_code: str,
                              currency: str = "NGN") -> str | None:
    """
    Create a transfer recipient on Paystack.
    Returns recipient_code or None.
    Docs: https://paystack.com/docs/api/transfer-recipient/#create
    """
    try:
        response = requests.post(
            f"{PAYSTACK_BASE_URL}/transferrecipient",
            json={
                "type": "nuban",
                "name": account_name,
                "account_number": account_number,
                "bank_code": bank_code,
                "currency": currency,
            },
            headers=_headers(),
            timeout=30
        )
        data = response.json()
        if data.get("status"):
            return data["data"]["recipient_code"]
        logger.error("Paystack recipient creation failed: %s", data)
    except Exception as exc:
        logger.exception("Paystack recipient error: %s", exc)
    return None


def initiate_transfer(amount_kobo: int, recipient_code: str,
                      reference: str, reason: str = "") -> dict | None:
    """
    Initiate a Paystack transfer to a recipient.
    Docs: https://paystack.com/docs/api/transfer/#initiate
    """
    try:
        response = requests.post(
            f"{PAYSTACK_BASE_URL}/transfer",
            json={
                "source": "balance",
                "amount": amount_kobo,
                "recipient": recipient_code,
                "reason": reason,
                "reference": reference,
            },
            headers=_headers(),
            timeout=30
        )
        data = response.json()
        if data.get("status"):
            return data["data"]
        logger.error("Paystack transfer failed: %s", data)
    except Exception as exc:
        logger.exception("Paystack transfer error: %s", exc)
    return None


def list_banks(country: str = "nigeria") -> list:
    """
    Fetch list of supported banks.
    Docs: https://paystack.com/docs/api/miscellaneous/#bank
    """
    try:
        response = requests.get(
            f"{PAYSTACK_BASE_URL}/bank",
            params={"country": country, "per_page": 100},
            headers=_headers(),
            timeout=30
        )
        data = response.json()
        if data.get("status"):
            return data["data"]
    except Exception as exc:
        logger.exception("Paystack list banks error: %s", exc)
    return []


def resolve_account(account_number: str, bank_code: str) -> dict | None:
    """
    Resolve/verify a bank account number.
    Docs: https://paystack.com/docs/api/verification/#resolve-account
    """
    try:
        response = requests.get(
            f"{PAYSTACK_BASE_URL}/bank/resolve",
            params={
                "account_number": account_number,
                "bank_code": bank_code
            },
            headers=_headers(),
            timeout=30
        )
        data = response.json()
        if data.get("status"):
            return data["data"]
        logger.error("Paystack resolve account failed: %s", data)
    except Exception as exc:
        logger.exception("Paystack resolve account error: %s", exc)
    return None
