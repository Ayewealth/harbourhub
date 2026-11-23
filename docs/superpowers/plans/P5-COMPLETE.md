# P5 — Zero-debt alignment completion record

**Design:** [`../specs/2026-11-02-harbour-hub-zero-debt-alignment-design.md`](../specs/2026-11-02-harbour-hub-zero-debt-alignment-design.md) (`99ab351`)  
**Plan:** [`2026-11-02-harbour-hub-p5-zero-debt-alignment.md`](2026-11-02-harbour-hub-p5-zero-debt-alignment.md) (`d1e5add`)  
**Completed:** 2026-11-09

---

## Task table

| Task | Commit | Date | Full suite after commit | Focused verification |
|---|---|---|---|---|
| 1 — Platform config on the listing lifecycle and public reads | `9e27772` | 2026-11-06 | 199 passed | Listing create/update/publish, public list/detail/store/category filtering, `GET /platform-config/` |
| 2 — Vendor approval and the verification response | `5e98106` | 2026-11-06 | 202 passed | Verification auto-approval, store verification, 201 response shape |
| 3 — Seller delivery rates and the invoice | `3341e90` | 2026-11-06 | 209 passed | Delivery-zone matching, free-shipping threshold, invoice line items |
| 4 — Payout and dispute state machines | `0948dcd` | 2026-11-06 | 220 passed | `VendorEarning.PROCESSING`, `Dispute.REFUNDED`, `Dispute.CANCELLED` |
| 5 — Web push, preferences, Termii-only SMS | `bd7ce5f` | 2026-11-09 | 232 passed | VAPID adapter, subscription deactivation, preference rules, SMS adapter |
| 6 — Social login, admin coverage, real metrics | `31a0992` | 2026-11-09 | 278 passed | Google/Apple token validation, admin registrations, analytics export aggregates |
| 7 — Canonical routes and response contracts | `4e26cff` | 2026-11-09 | 289 passed | `test_routes.py`, `test_sessions.py`, `test_order_contract.py`, `test_financial_contract.py` |
| 8 — Configuration, CI/deploy, documentation | `f590e2e` | 2026-11-09 | 291 passed | `pytest tests/test_check_paystack_config.py` |
| 9 — Production deployment and Paystack live cutover | `6235c36`, `ad43c98` (deploy) | 2026-11-10 | 291 passed | `check_paystack_config`, `--send-signed-event`, live route checks |

The full-suite count is the repository-wide `pytest -q` result immediately after each task. Focused
modules are the files added or extended by that task; they are part of the same full-suite run.

---

## Task 8 gate results

| Gate | Command | Result |
|---|---|---|
| Focused config test | `python -m pytest tests/test_check_paystack_config.py -q` | **2 passed** |
| Full suite | `python -m pytest -q` | **291 passed** (2 third-party deprecation warnings) |
| Django system check | `python manage.py check` | **No issues** |
| Migration drift | `python manage.py makemigrations --check --dry-run` | **No changes detected** |
| Undefined names / unused imports | `python -m flake8 apps hb tests --select=F401,F821,F841 --exclude=migrations` | **Clean** |
| OpenAPI validation | `python manage.py spectacular --file schema.yml --validate` | **Valid** |
| Endpoint reference | `python scripts/generate_api_reference.py` | **272 operations written** |

The regenerated `schema.yml` contains `/platform-config/`, `/commerce/webhooks/paystack/`, the
deprecated `/commerce/payment/webhook/` alias, `/analytics/`, the legacy `/analytics/analytics/`
alias, and every notification preference and push-subscription path.

The schema also now states the real authentication requirement: 36 genuinely public operations
(registration and login flows, public catalogue reads, webhooks, support contact, push public key,
and admin-invite acceptance) carry no security requirement, while every authenticated operation
retains `Bearer JWT`. Before this correction the generated reference advertised a bearer token on
public endpoints, which would have led clients to send credentials they do not need.

---

## Verified in this repository

These behaviours are covered by tests and do not need a live third-party account:

- Platform switches gate listing creation, seller `status` changes, the publish action, the public
  listing/detail/recommendation/store/category surfaces, and the Django admin bulk publish action.
- The client cannot set `Listing.store`; the server always assigns the seller's store.
- `listing_approval_required` keeps a seller listing in `draft` and rejects publish until an admin
  approves it.
- `vendor_approval_required=false` auto-approves the verification request and verifies the store.
- Buyers are never charged a platform or escrow fee; `commission_rate` and `commission_amount` are
  returned, and `escrow_fee` remains as a deprecated compatibility field.
- Checkout resolves the seller's active shipping zone, charges the flat rate once per line, honours
  the free-shipping threshold, and leaves service or address-less lines free.
- Payout allocation moves earnings to `processing`; settlement and failure unwind them; a full refund
  closes an open dispute as `refunded`; buyers can cancel their own disputes.
- In-app, email, Termii SMS, VAPID web push, and staff-webhook adapters record `sent`, `failed`, or
  `skipped` truthfully; preferences enforce the transactional rule.
- Google and Apple login validate the configured client id, issuer, verified email, and Apple's
  signature; every business model is registered in the Django admin.
- The analytics export computes real aggregates for the requested range.
- Canonical routes and deprecated aliases resolve; login stores `device_type`; order responses expose
  integer `order_id`; quote action messages are grammatical.
- `check_paystack_config` rejects test keys and accepts live prefixes once supplied.
- The canonical webhook endpoint accepts a correctly signed event and records exactly one
  `WebhookEvent` row; the signed self-test was accepted in production and mutated nothing.

---

## Proven in production

- Deployment of `ad43c98` to `api.harbourhubglobal.com` with all 22 migrations applied.
- All four services active, `/api/docs/`, `/platform-config/`, `/notifications/push/public-key/`,
  `/listings/`, `/stores/`, and `/categories/` returning `200`.
- Canonical `/commerce/webhooks/paystack/` and the deprecated `/commerce/payment/webhook/` alias both
  reject unsigned requests with `401`.
- Live `sk_live_…`/`pk_live_…` keys and the canonical `PAYSTACK_WEBHOOK_URL` resolve in the running
  process, and `check_paystack_config` passes.
- The Live Webhook URL is registered in the Paystack dashboard.
- A signed self-test webhook was accepted and recorded as `WebhookEvent` `id 1` with status
  `ignored`; no payment or order was created or changed.
- Celery Beat is scheduling: `django_celery_beat` `PeriodicTask.last_run_at` advanced to
  `2026-11-10 12:20:00 UTC` for `compute-analytics-snapshot` and
  `reconcile-pending-payments-every-five-minutes`, to `12:00:00 UTC` for the hourly listing,
  earnings, and rental-advance tasks, to `08:00:00 UTC` for the rental reminders, and to
  `01:00:00 UTC` for compliance statuses.
- The worker consumes the broker: dispatching `compute_and_cache_analytics` on the live host
  returned `ok` (task id `774391e7-a3c0-423b-a7e3-33191129a32b`). Task success is not written to
  the worker journal because production runs at `WARNING`, so this call is the direct evidence.
- Web Push is configured: a VAPID key pair was generated, the public key is served by
  `GET /notifications/push/public-key/` with `configured: true`, and the private PEM lives at
  `/var/www/harbourhub/.vapid_private.pem` (mode `600`, owner `ubuntu`). A probe push signed with
  that key reached the transport layer and failed only at DNS resolution for a placeholder
  endpoint, so key loading, encryption, and JWT signing work. No real browser subscription has
  received a push yet.
- Google social login is configured: `GOOGLE_CLIENT_ID` is set in production, and
  `POST /auth/social/google/` now returns `400` (`Either id_token or access_token is required.`)
  instead of `503`. Invalid tokens are rejected with `400 Invalid Google token.` A successful
  exchange with a real Google-issued token has not been exercised. Apple remains intentionally
  unconfigured and returns `503`.

---

## Money and order-state fixes (2026-11-20)

Deployed `d8b3a2b` with migration `commerce.0015_order_expected_delivery_date` applied. The four
services restarted and stayed active. Verified live:

- `GET /currency/rates/?from=NGN&to=USD&amount=150000` returns a fresh
  `source: "open.er-api.com"`, `stale: false` snapshot and a `conversion` result, so the client and
  the server now read the same numbers.
- `/listings/`, `/platform-config/`, and `/commerce/quotes/` respond as before (`200`/`401`), and
  the web and worker journals have no warnings since the restart.
- All 321 tests pass locally, including the new money, tracking, receipt, and Paystack-limit
  cases, and `manage.py check`, `makemigrations --check`, the flake8 F gate, and schema validation
  are clean.

Not yet exercised against real production data:

- Buying an order through `confirm-receipt` from `item_dispatched`/`in_transit` (covered by tests;
  no live order was changed).
- A seller PATCH containing all four new delivery fields (covered by tests; no live order was
  changed).
- A checkout above `PAYSTACK_MAX_TRANSACTION_NGN` being refused by the live gateway path. The
  guard is proven before order creation in tests; the live refusal was not provoked because it
  would require a real high-value checkout.
- Historical quotes are not rewritten. Some July/August test quotes were created when the same
  listings were priced in NGN and later switched to USD, so their stored `standard_price` reflects
  the old listing currency. They belong to the owner's test accounts and the `@yopmail.com` test
  buyer. The one non-test buyer (`victoremeka788@gmail.com`) has a cancelled quote whose shipping
  figure may have been typed in NGN, but nothing was charged from it; the other quote became an
  order with zero shipping, so its amounts are unaffected.

---

## Requires staging or a real customer transaction

The following need a real third-party event and could not be proven without one:

- Live Paystack rental-extension, refund, and transfer webhooks (the self-test covers only the
  signature and ledger path).
- Real Paystack transfers and settlement.
- The first real live charge appearing as delivered in the Paystack dashboard, matched to a local
  `WebhookEvent` row.
- Termii SMS delivery to a real handset.
- Real browser web push delivery through a browser push service.
- Production-volume admin payment listing and export.
- The P0 manual acceptance checklist on a deployed environment.

---

## Paystack cutover status (Task 9)

**Complete.** Production runs live Paystack keys, the canonical webhook URL is registered in the
Paystack dashboard, and a signed self-test webhook was accepted and recorded without mutating data.

### Inspection before deployment (2026-11-10)

| Check | Result |
|---|---|
| Deployed commit | `0f6d8f9` (`origin/main`), **68 commits behind this branch** |
| Services | `harbourhub-web`, `harbourhub-worker`, `harbourhub-beat`, `nginx` — all active |
| Python | 3.12.3 |
| Migrations pending on the deployed code | none (`migrate --plan`: no operations) |
| New migrations in the undeployed branch | 22 |
| `PAYSTACK_SECRET_KEY` | `sk_test_…` |
| `PAYSTACK_PUBLIC_KEY` | `pk_test_…` |
| `PAYSTACK_WEBHOOK_URL` | absent from the environment file |
| `POST /commerce/webhooks/paystack/` | `404` (route not deployed) |
| `POST /commerce/payment/webhook/` | `400` (legacy route exists) |
| Platform flags | buy on, rent on, services off, vendor approval on, listing approval off |

The plan's precondition — Task 8 deployed to `api.harbourhubglobal.com` — was not met. Deployment
was a production change, and the owner approved it.

### Deployment (2026-11-10)

- CI succeeded for `ac180ac`. The first deploy failed before touching the host because the new
  `EC2_HOST`, `EC2_USER`, and `EC2_PATH` secrets were not configured. Commit `6235c36` keeps those
  secrets as optional overrides with the known-working defaults.
- CI and Deploy succeeded for `6235c36`.
- Verified on the host: HEAD `6235c36`, all four services active, `migrate --plan` reports no
  operations, and `/api/docs/`, `/platform-config/`, `/notifications/push/public-key/`, `/listings/`,
  `/stores/`, and `/categories/` return `200`.
- Both webhook paths now return `401` for an unsigned request, so the canonical route is live.
- `check_paystack_config` correctly rejected the test keys that were still in place at that point.

### Live cutover (2026-11-10)

- The owner replaced `PAYSTACK_SECRET_KEY` and `PAYSTACK_PUBLIC_KEY` with the live values and set
  `PAYSTACK_WEBHOOK_URL=https://api.harbourhubglobal.com/commerce/webhooks/paystack/` in
  `/var/www/harbourhub/.env` (lines 85, 86, and 88), then restarted all four services.
- The running process resolves `sk_live_…` and `pk_live_…` and the canonical webhook URL.
- `check_paystack_config` passed: “Paystack keys and webhook URL look valid.”
- `check_paystack_config --send-signed-event` passed: “Signed non-mutating webhook accepted.”
- The signed self-test recorded `WebhookEvent` `id 1` — provider `paystack`, event
  `charge.success`, gateway id `p5-self-test-1fed1f2ac7164a32`, status `ignored` — at
  `2026-11-10 11:58:44 UTC`.
- No mutation: `Payment.objects.filter(reference__startswith="P5-SELFTEST").count()` is `0`;
  payments stayed at 11 and orders stayed at 11.
- The owner registered the same URL as the **Live Webhook URL** in the Paystack dashboard.

The only unverified step left is the owner's first real live charge: confirm it appears as
delivered in the Paystack dashboard and matches a local `WebhookEvent` row. Everything the
application can prove without a real customer charge is proven.

### Remaining handoff (client-owned)

1. Make the first real live charge and confirm the Paystack dashboard shows the event delivered.
2. Confirm a matching `WebhookEvent` row exists locally and that the order reaches its paid state.

Until that first charge is observed, the live delivery side is unproven; the endpoint, signature
verification, and ledger write are proven by the signed self-test.

---

## Post-completion follow-ups

- **Checkout body has no `delivery_detail_id`.** This was already true at completion: each cart item
  carries its own `delivery_detail`, and `CheckoutSerializer` accepts only `cart_item_ids`,
  `payment_method`, and `terms_accepted`. Sending an extra top-level key is ignored by DRF, so the
  field is effectively optional. Documented in [`docs/api/examples.md`](../../api/examples.md).
- **Order list summary carries money and quantity.** `OrderListTrackingSummarySerializer` already
  returned `total_amount`; it now also returns `currency` and `quantity` (the sum of the order's item
  quantities), so the My Orders table no longer needs hardcoded zeros. Covered by
  `tests/test_order_serializers.py`.
- **Google access tokens are accepted.** The `access_token` branch already existed but rejected
  Google's response because the access-token `tokeninfo` payload has no `iss` claim. The issuer
  check now applies only to ID tokens, the audience check accepts `aud`, `audience`, or `issued_to`,
  `azp` is checked when present, and the verified-email check accepts `email_verified` or the legacy
  `verified_email`. Covered by `tests/test_social_auth.py`.
- **Payout safety and the admin payout list (2026-11-21).** `a59d90f` deployed the payout fixes and
  `0d93c2f` fixed null bank fields in the admin list. Migrations `notifications.0005` and
  `admin_panel.0011` are applied.
  - `POST /financials/payouts/` resolves the supplied bank account or the vendor's default and
    returns `400` before writing any payout or wallet row when neither exists, or when the amount
    exceeds `available_balance`.
  - An immediate `process_payout_task` failure now calls `fail_payout` instead of only marking the
    row failed. Transfers are not retried automatically (a timed-out request may already be
    accepted). `fail_payout` is idempotent, and a reversal after `paid` unwinds
    `total_withdrawn`/`paid_out_amount`; a late success after `failed` re-debits before settling.
  - `GET /admin-panel/payments/payouts/` exposes vendor/store identity, bank details, amount,
    currency, status, `failure_reason`, reference, receipt, and timestamps, with `status`, `vendor`,
    `store`, `date_from`, `date_to`, and search filters. Admin in-app/email/push notifications fire
    on payout request and failure.
  - Live repair: failed payout #1 (`PO-807CDDDC6227`, OceanRig Energy Solutions Ltd, store 11) had
    no bank account and the pre-fix task left it failed without a refund. Restored NGN 1,027.61 to
    wallet 11 (`WalletTransaction` #4, `refund`), cleared its allocation, returned earning #1 to
    `available`, and recorded `AdminActionLog` #29 (`payout_restored`). No other payout had an
    unrefunded failure and no data was reset.
  - Verified live after the restart: HEAD `0d93c2f`, all four services active, worker `ping` OK,
    `nginx -t` OK, `/listings/`, `/platform-config/`, `/currency/rates/`, `/api/schema/`, and
    `/api/docs/` return `200`; the admin payout list returns `200` with explicit `null` bank fields;
    a no-bank payout request returns `400` with $0 balance change and no payout row.
  - Not live-proven: a real `transfer.failed`/`transfer.reversed` webhook and admin email/push
    delivery. Those paths are covered by tests only.
- **Wallet transaction currency and payout failure recovery (2026-11-23).** `0e75d95` fixes two
  production-money bugs found while investigating payout #2; 333 tests pass.
  - `WalletTransaction` has no currency column, so `resolve_source_currency` now falls back to
    `wallet.currency`, and `WalletTransactionSerializer` declares `currency`. A wallet movement
    stored as NGN is no longer treated as USD and multiplied by the USD→NGN rate.
  - `process_payout_task` now reduces Paystack errors to `message (code)` instead of storing the
    whole response, and `fail_payout` caps the refund transaction description at 255 characters.
    A verbose gateway error can no longer roll back the status change and refund.
  - Paystack can hold a transfer for OTP (`data.status == "otp"`). That response is now failed and
    refunded with a clear reason instead of being reported to the vendor as processing. If the held
    transfer is finalized later, the existing `transfer.success` re-debit prevents a double payout.
  - Root cause of payout #2 (`PO-A9DF440ABF5A`, OceanRig): the worker ran the task, Paystack created
    recipient `RCP_bs0r2tikhe1cs84`, then rejected the transfer with `insufficient_balance` because
    the live Paystack balance is NGN 0. The full error dict overflowed `WalletTransaction.description`,
    so the atomic failure path rolled back and the payout stayed `requested`.
  - Live repair: payout #2 is `failed` with the real reason, allocations are cleared, wallet 11 is
    back to NGN 1,027.61, `WalletTransaction` #6 is a single `refund`, and vendor/admin failure
    notifications exist. A second `fail_payout` left the balance and refund count unchanged.
  - Verified live at HEAD `0e75d95`: all four services active, worker `ping` OK,
    `/financials/wallet/` returns `1027.61 NGN` (`source_currency` NGN), and
    `/financials/wallet/transactions/` returns the refund and payout rows as NGN amounts. Public
    `/listings/`, `/platform-config/`, `/currency/rates/`, `/api/schema/`, and `/api/docs/` return
    `200` on `api.harbourhubglobal.com`.
  - Not live-proven: a funded Paystack transfer, transfer OTP finalization, and the live webhook
    outcome. Paystack balance must be funded (amount plus transfer fee) and Transfers OTP disabled
    for automated payouts before a payout can complete.

---

## Deferred product work

Advertisements, premium users, and real-time chat are documented, with their current state and the
reason for deferral, in [`../../product/future-backlog.md`](../../product/future-backlog.md). Social
login is listed there only to record that it is implemented and retained, not deferred.
