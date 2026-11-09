import hashlib
import hmac
import json
import secrets
import urllib.error
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

EXPECTED_WEBHOOK = (
    "https://api.harbourhubglobal.com/commerce/webhooks/paystack/"
)


class Command(BaseCommand):
    help = "Validate Paystack live keys and the deployed webhook endpoint."

    def add_arguments(self, parser):
        parser.add_argument(
            "--send-signed-event",
            action="store_true",
            help="POST a signed, non-mutating charge.success event.",
        )

    def handle(self, *args, **options):
        secret = getattr(settings, "PAYSTACK_SECRET_KEY", "")
        public = getattr(settings, "PAYSTACK_PUBLIC_KEY", "")
        webhook = getattr(settings, "PAYSTACK_WEBHOOK_URL", "")

        problems = []
        if not secret.startswith("sk_live_"):
            problems.append("PAYSTACK_SECRET_KEY is not a live secret key.")
        if not public.startswith("pk_live_"):
            problems.append("PAYSTACK_PUBLIC_KEY is not a live public key.")
        if webhook != EXPECTED_WEBHOOK:
            problems.append(
                f"PAYSTACK_WEBHOOK_URL must be {EXPECTED_WEBHOOK}."
            )
        if problems:
            raise CommandError(" ".join(problems))

        self.stdout.write(self.style.SUCCESS(
            "Paystack keys and webhook URL look valid."
        ))
        if not options["send_signed_event"]:
            return

        unsigned = urllib.request.Request(
            webhook,
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(unsigned, timeout=15)
        except urllib.error.HTTPError as exc:
            if exc.code != 401:
                raise CommandError(
                    f"Unsigned probe returned {exc.code}, expected 401."
                )
        except Exception as exc:
            raise CommandError(f"Unsigned probe failed: {exc}")

        payload = {
            "event": "charge.success",
            "data": {
                "id": f"p5-self-test-{secrets.token_hex(8)}",
                "reference": f"P5-SELFTEST-{secrets.token_hex(6)}",
                "amount": 1,
                "status": "success",
            },
        }
        body = json.dumps(payload).encode("utf-8")
        signature = hmac.new(
            secret.encode("utf-8"), body, hashlib.sha512
        ).hexdigest()
        signed = urllib.request.Request(
            webhook,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "x-paystack-signature": signature,
            },
        )
        try:
            response = urllib.request.urlopen(signed, timeout=15)
        except urllib.error.HTTPError as exc:
            raise CommandError(
                f"Signed probe returned {exc.code}, expected 200."
            )
        except Exception as exc:
            raise CommandError(f"Signed probe failed: {exc}")

        if response.status != 200:
            raise CommandError(
                f"Signed probe returned {response.status}, expected 200."
            )
        self.stdout.write(self.style.SUCCESS(
            "Signed non-mutating webhook accepted."
        ))
