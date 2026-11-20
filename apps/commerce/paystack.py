import requests
import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings

logger = logging.getLogger(__name__)

PAYSTACK_BASE_URL = "https://api.paystack.co"

# Paystack's default per-transaction ceiling for a Nigerian business. A
# merchant whose limit has been raised can set PAYSTACK_MAX_TRANSACTION_NGN.
DEFAULT_MAX_TRANSACTION_NGN = 10_000_000


class PaystackAmountLimitExceeded(ValueError):
    """The amount is larger than Paystack will accept in one transaction."""

    def __init__(self, amount_kobo: int, limit_kobo: int):
        self.amount_kobo = amount_kobo
        self.limit_kobo = limit_kobo
        super().__init__(
            "This amount of NGN "
            f"{amount_kobo / 100:,.2f} exceeds Paystack's per-transaction "
            f"limit of NGN {limit_kobo / 100:,.2f}. Split the purchase into "
            "smaller payments or ask us to complete a bank transfer."
        )


def max_transaction_kobo() -> int:
    """The configured Paystack per-transaction limit, in kobo."""
    raw = getattr(
        settings,
        "PAYSTACK_MAX_TRANSACTION_NGN",
        DEFAULT_MAX_TRANSACTION_NGN,
    )
    try:
        naira = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        naira = Decimal(DEFAULT_MAX_TRANSACTION_NGN)
    return int(naira * 100)


def ensure_amount_within_limit(amount_kobo: int) -> None:
    if amount_kobo <= 0:
        raise ValueError("Payment amount must be greater than zero.")
    limit = max_transaction_kobo()
    if amount_kobo > limit:
        raise PaystackAmountLimitExceeded(amount_kobo, limit)


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
    ensure_amount_within_limit(amount_kobo)

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
