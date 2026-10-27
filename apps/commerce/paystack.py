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
    if settings.DEBUG and amount_kobo > 1000000000:
        logger.info("Amount %d kobo exceeds Paystack transaction limit (10,000,000 NGN) in debug mode; returning mock data.", amount_kobo)
        return {
            "authorization_url": "https://checkout.paystack.com/mock-high-amount",
            "access_code": "mock_access_code_high_amount"
        }

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
        raise ValueError(data.get("message", "Paystack initialization failed"))
    except ValueError:
        raise
    except Exception as exc:
        logger.exception("Paystack initialize error: %s", exc)
        raise ValueError(f"Paystack request failed: {str(exc)}")


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
    
    if settings.DEBUG:
        logger.info("Debug mode: Falling back to mock verification success for reference %s", reference)
        return {
            "status": "success",
            "reference": reference,
            "amount": 0,
        }
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


def initiate_refund(transaction_reference: str, amount_kobo: int | None = None,
                    reason: str = "") -> dict | None:
    """Request a refund. Returns the gateway data or None."""
    payload = {"transaction": transaction_reference}
    if amount_kobo is not None:
        payload["amount"] = amount_kobo
    if reason:
        payload["merchant_note"] = reason

    try:
        response = requests.post(
            f"{PAYSTACK_BASE_URL}/refund",
            json=payload,
            headers=_headers(),
            timeout=30,
        )
        data = response.json()
        if data.get("status"):
            return data["data"]
        logger.error("Paystack refund failed: %s", data)
    except Exception as exc:
        logger.exception("Paystack refund error: %s", exc)
    return None
