# Harbour Hub P4 — Documentation and Remaining Debt

> **Spec:** `docs/superpowers/specs/2026-10-26-harbour-hub-connectivity-design.md` §14.
> **Predecessors:** `P0-COMPLETE.md`, `P1-COMPLETE.md`, `P2-COMPLETE.md`, `P3-COMPLETE.md`.
> **Branch:** `main`.

## Goal

P0–P3 fixed the behaviour. P4 makes the platform **understandable and verifiable**: the remaining
test debt is closed, the suite is offline-safe, and the API is documented end to end — the schema,
every endpoint, every success and error message, the data model, and the sample data.

P4 does **not** add product features. New feature ideas (advertisements, premium users, social
login, realtime chat) are outside the connectivity spec and need their own plan.

**Hard rules carried forward**

- Never delete or rewrite live data. Migrations are additive and guarded.
- One task, one commit. Run the full gate before each commit.
- `python -m flake8` (flake8 is not on `PATH`).
- Documentation must describe the code that exists, not an aspiration. Every example is either
  taken from a test or produced by the sample-data command.

## Baseline (at `fc26451`)

| Metric | Value |
|---|---|
| `pytest` | 150 passed |
| Uncollected app tests | 9 `apps/*/tests_comprehensive.py` modules (15 pass, 8 fail when run directly) |
| Offline risk | `CurrencyConverterMixin` can call `open.er-api.com` on a cold cache |
| Schema | 192 paths, 259 operations, 0 warnings, 0 errors, no tag descriptions |
| Documentation | phase records only; no API reference, error catalogue, data-model or sample-data guide |

---

## Task 1 — Adopt and repair the uncollected app tests

**Why:** `pytest.ini` sets `testpaths = tests`, so nine `apps/*/tests_comprehensive.py` modules
never run. They contain real edge-case coverage (ownership, unique constraints, payout limits,
notification isolation) that is currently invisible.

**Files**

- Create: `tests/test_accounts_comprehensive.py`, `tests/test_categories_comprehensive.py`,
  `tests/test_commerce_comprehensive.py`, `tests/test_financials_comprehensive.py`,
  `tests/test_inquiries_comprehensive.py`, `tests/test_listings_comprehensive.py`,
  `tests/test_notifications_comprehensive.py`, `tests/test_reviews_comprehensive.py`,
  `tests/test_store_comprehensive.py`
- Delete: the nine `apps/*/tests_comprehensive.py` modules

**Steps**

1. Move each module into `tests/` unchanged first, then repair the eight failures against the P2/P3
   model:
   - `Listing.store` is mandatory: create a `Store` in review/listing fixtures.
   - Commerce checkout uses one order per cart item and a `CheckoutSession`; update assertions.
   - Inquiry creation assigns `sender`, not a removed field; reply sets `status=replied`.
   - Listing expiry/soft-delete assertions follow the current `Listing.Status` values.
2. Keep the assertions that still express a real invariant; delete assertions that only pinned a
   removed implementation detail.
3. Run the full suite; the count must rise by the adopted tests.

**Commit:** `test: adopt and repair the uncollected app test modules`

---

## Task 2 — Make the suite offline-safe

**Why:** `CurrencyConverterMixin.to_representation` calls `convert_currency`, which calls
`get_exchange_rates`. On a cold cache that performs a live HTTP request to `open.er-api.com`, so a
test run depends on the network.

**Files**

- Modify: `tests/conftest.py`
- Modify: `hb/settings_test.py` (deterministic rate cache, not a code branch)

**Steps**

1. Add an autouse fixture that seeds the exchange-rate cache with fixed USD-base rates before any
   test touches a serializer. Use the cache key `harbour_hub_exchange_rates_usd`.
2. Keep `tests/test_currency.py` patching `get_exchange_rates` directly; the fixture must not hide
   a missing-rate path.
3. Add a regression test that asserts a serialized monetary response works with the network layer
   patched to raise, proving no test can reach the provider.
4. Document the fixed rates in `docs/sample-data.md`.

**Commit:** `test: seed deterministic exchange rates so the suite is offline-safe`

---

## Task 3 — Schema metadata and a generated endpoint reference

**Why:** the OpenAPI file is valid but hard to read: no tag descriptions, no server/contact
metadata, and no human-readable index of 259 operations.

**Files**

- Modify: `hb/settings.py` (`SPECTACULAR_SETTINGS`)
- Create: `scripts/generate_api_reference.py`
- Create: `docs/api/endpoints.md` (generated)
- Create: `docs/api/README.md`

**Steps**

1. Add `TAGS` with a one-line description for every tag (`auth`, `listings`, `stores`, `commerce`,
   `quotes`, `financials`, `notifications`, `messages`, `inquiries`, `reviews`, `categories`,
   `admin-panel`, `analytics`, `compliance`, `support`, `search`, `careers`).
2. Add `CONTACT`, `LICENSE`, `SERVERS`, and a multi-paragraph `DESCRIPTION` covering auth, money,
   pagination, and the error envelope.
3. Write `scripts/generate_api_reference.py`: read `schema.yml`, group operations by tag, and emit
   a Markdown table per tag with method, path, operation id, summary, auth, and success codes.
4. Generate `docs/api/endpoints.md` and commit it. The script is deterministic, so CI or a
   reviewer can regenerate it.
5. Write `docs/api/README.md`: base URL, versioning, auth flow, pagination, filtering, money and
   currency, status enums, idempotency, rate limits, and where the other documents live.

**Commit:** `docs(api): add schema metadata and a generated endpoint reference`

---

## Task 4 — Error and success message catalogue

**Why:** clients need the exact strings and status codes the API returns. Today they are scattered
across views, serializers, services, and the webhook.

**Files**

- Create: `docs/api/messages.md`
- Create: `tests/test_documented_messages.py`

**Steps**

1. Catalogue, per domain: HTTP status, the JSON shape (`{"error": ...}`, `{"message": ...}`,
   DRF field errors), the exact message, and the trigger.
2. Cover the cross-cutting responses: `400` validation, `401` unauthenticated, `403` forbidden,
   `404` not found, `405` method not allowed, `429` throttled, `500`/`502`/`503` gateway and
   server errors.
3. Cover the domain messages from the audit: auth/OTP/2FA, onboarding, listings, store, cart,
   checkout/payment, orders/rentals, quotes, disputes, reviews, messaging/inquiries,
   notifications, financials/payouts, admin, compliance, support, search.
4. Add `tests/test_documented_messages.py`: assert the highest-value messages still exist verbatim
   (import the view module and inspect source constants or hit the endpoint). This keeps the
   catalogue from drifting silently.

**Commit:** `docs(api): catalogue success and error messages and pin them with tests`

---

## Task 5 — Data model, sample data, and worked examples

**Why:** the schema says what the wire looks like, not how the domain fits together or what a real
payload contains.

**Files**

- Create: `docs/data-model.md`
- Create: `docs/sample-data.md`
- Create: `docs/api/examples.md`

**Steps**

1. `docs/data-model.md`: every entity, its key fields, relationships, and the invariants that
   matter (one cart item = one order, store is the vendor, commission on goods only, 50/50
   tranches, one wallet per store, rental dates only after payment, notification delivery ledger).
   Include an ASCII relationship diagram and the status machines for `Order`, `Payment`,
   `VendorEarning`, `Payout`, `Refund`, `QuoteRequest`, `Dispute`, and `RentalExtension`.
2. `docs/sample-data.md`: what `create_sample_data` creates, the deterministic natural keys, the
   accounts and passwords it prints, how to run it safely (`SEED_SAMPLE_DATA=true` / `--force`),
   and how to verify it (money invariants, no duplicates on re-run).
3. `docs/api/examples.md`: end-to-end worked examples with real JSON:
   - register → login → refresh → logout;
   - create a store → create a listing → upload an image;
   - add to cart → checkout → webhook → order paid → earning accrued;
   - ship → deliver → confirm receipt → final tranche released;
   - extend a rental and pay;
   - request a quote → respond → move to cart;
   - open a dispute → admin resolves;
   - request a payout → transfer success/failure;
   - notification preferences and the delivery ledger.
   Each example states the request, the success response, and the common error responses.
4. Cross-link the documents from `docs/README.md` and `docs/api/README.md`.

**Commit:** `docs: add the data model, sample data, and worked API examples`

---

## Task 6 — Final gate and completion record

**Files**

- Create: `docs/superpowers/plans/P4-COMPLETE.md`
- Regenerate: `schema.yml`

**Steps**

1. Run the full gate.
2. Regenerate `schema.yml` and confirm `Warnings: 0`, `Errors: 0`.
3. Write `P4-COMPLETE.md` with the commit table, final counts, documentation index, and the
   staging-only list carried forward from P3.
4. Record any remaining debt honestly.

**Commit:** `docs: record P4 completion and verification`

---

## Verification checklist

- [ ] `python manage.py check` clean
- [ ] `python manage.py makemigrations --check --dry-run` clean
- [ ] `python -m pytest -q` green, with the adopted app tests included
- [ ] `python -m flake8 apps hb tests --select=F401,F821,F841 --exclude=migrations` clean
- [ ] `python manage.py spectacular --file schema.yml --validate` 0 errors, 0 warnings
- [ ] `docs/api/endpoints.md` regenerates without a diff
- [ ] Every documented message has a test or a code reference
- [ ] No data deleted, no migration faked, no table dropped
- [ ] Every task committed separately
