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

---

## Requires staging

The following need a real deployment or third-party credentials and could not be proven locally:

- Real Paystack rental-extension, refund, and transfer webhooks.
- Real Paystack transfers and the dashboard webhook registration.
- Termii SMS delivery to a real handset.
- Real browser web push delivery through a browser push service.
- Celery Beat scheduling under the production worker and beat services.
- Production-volume admin payment listing and export.
- The P0 manual acceptance checklist on a deployed environment.

---

## Paystack cutover status (Task 9)

**Blocked; not started.** A read-only inspection of the live host on 2026-11-10 found:

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

The plan's precondition — Task 8 deployed to `api.harbourhubglobal.com` — is not met. Deployment is
a production change: the 68 commits include 22 migrations and a new `health` app. It needs explicit
approval before the branch is pushed and the deploy workflow runs.

The cutover also needs live `sk_live_…` and `pk_live_…` values delivered through a secure channel,
and the owner's Paystack dashboard access to register the live webhook URL.

Once those are available, the sequence is:

1. Push and deploy the branch so the canonical path exists; confirm migrations and service health.
2. Set `PAYSTACK_SECRET_KEY`, `PAYSTACK_PUBLIC_KEY`, and `PAYSTACK_WEBHOOK_URL` in the production
   environment.
3. Register `https://api.harbourhubglobal.com/commerce/webhooks/paystack/` in the Paystack dashboard.
4. Run `python manage.py check_paystack_config --send-signed-event` from the production host and
   record the result here.

Until then, production remains on test keys and the legacy webhook path.

---

## Deferred product work

Advertisements, premium users, and real-time chat are documented, with their current state and the
reason for deferral, in [`../../product/future-backlog.md`](../../product/future-backlog.md). Social
login is listed there only to record that it is implemented and retained, not deferred.
