# P0 complete

- Test harness and CI: `pytest`, PostgreSQL service, migration check, schema validation.
- Auth: registration forces buyer; token blacklist installed.
- Admin: dashboard staff identity and module matrix enforced on every endpoint.
- Listings: store derived server-side, backfilled, non-null.
- Verification: business type stored separately; fake document paths removed.
- Checkout: no buyer fee; rent maps to hire.
- Money: one earning per order; release/reversal services.
- Payments: single idempotent finalizer; webhook ledger; read-only verify; reconciler.
- Payouts: allocation-bound settlement; failure re-credit.
- Refunds: admin-only, gateway-backed, webhook-finalised.
- Health app removed; reconciliation command added.

## Verification run

```
python manage.py check                  # no issues
python manage.py makemigrations --check # no changes
pytest -q                               # 33 passed
flake8 apps hb --select=F821            # clean
```

## Manual acceptance (staging)

Still to be executed against a staging database with live-shaped data:

1. `POST /auth/register/` with `"role": "super_admin"` returns `400`.
2. A normal registration returns `201` with `role == "buyer"`.
3. Seller onboarding step 3 stores `business_type`, leaves `additional_info` empty, and
   the admin vendor drawer shows only real document URLs.
4. Listing create with another store's id saves under the seller's own store.
5. Rental checkout total equals subtotal and the order item is `hire`.
6. Duplicate `charge.success` produces one `WebhookEvent` and one `VendorEarning`.
7. `GET /commerce/payment/verify/<reference>/` on a pending payment returns
   `pending_confirmation` and leaves `Payment.status == "pending"`.
8. A payout has `PayoutAllocation` rows summing to its amount; marking it paid changes
   only those earnings.
9. A non-admin dispute action returns `403`; a support admin with manage permission causes
   a Paystack refund request and a `Refund` row.
10. `python manage.py reconcile_orders --dry-run` prints only expected changes.

Next: P1 (every 500 and dead feature).
