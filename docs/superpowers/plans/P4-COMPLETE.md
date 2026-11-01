# Harbour Hub P4 — Completion Record

> **Plan:** `docs/superpowers/plans/2026-10-30-harbour-hub-p4-documentation-and-debt.md` (committed `27bfa72`).
> **Spec:** `docs/superpowers/specs/2026-10-26-harbour-hub-connectivity-design.md` §14.
> **Predecessors:** `P0-COMPLETE.md`, `P1-COMPLETE.md`, `P2-COMPLETE.md`, `P3-COMPLETE.md`.
> **Branch:** `main`.

---

## Result

P4 closed the documentation and test debt that P0–P3 left behind. The nine uncollected
`apps/*/tests_comprehensive.py` modules now run from `tests/`, the suite is offline-safe, and the
API is documented end to end: the contract, every endpoint, every success and error string, the
data model, the sample dataset, and worked request/response examples for each core flow.

No product feature was added. No live data was deleted, no migration was faked, and no table was
dropped.

The suite is green at **187 passed**, with no pending migrations and a schema that validates with
zero errors and zero operation-id collisions.

| Gate | Result |
|---|---|
| `python manage.py check` | no issues |
| `python manage.py makemigrations --check --dry-run` | no changes |
| `python -m pytest -q` | 187 passed, 2 warnings |
| `python -m flake8 apps hb tests --select=F401,F821,F841 --exclude=migrations` | clean |
| `python manage.py spectacular --file schema.yml --validate` | exit 0, 0 errors, 0 warnings |
| `python scripts/generate_api_reference.py` | 259 operations, no diff |

| Metric | Baseline (`fc26451`) | After P4 |
|---|---|---|
| `pytest` | 150 passed | 187 passed |
| Uncollected app tests | 9 modules (15 pass / 8 fail when run directly) | 0 — adopted into `tests/` |
| Offline risk in serializers | live `open.er-api.com` call on a cold cache | fixed rates seeded before every test |
| OpenAPI | 192 paths / 259 operations, no tag descriptions | 192 paths / 259 operations, tags, contact, licence, servers, description |
| API documentation | none | 6 documents under `docs/` |

The two remaining pytest warnings are third-party: a `reportlab`/`ast.NameConstant`
`DeprecationWarning`, and an `UnorderedObjectListWarning` on `AdminActionLog` pagination (recorded
as debt below).

---

## Commits

| Task | Commit | What changed |
|---|---|---|
| Plan | `27bfa72` | P4 plan |
| 1 | `3a293f5` | moved 9 `apps/*/tests_comprehensive.py` modules into `tests/` and repaired 8 failures |
| 2 | `81192ea` | autouse fixed exchange-rate fixture; offline regression test |
| 3 | `c3c50b6` | schema metadata, `scripts/generate_api_reference.py`, `docs/api/endpoints.md`, `docs/api/README.md` |
| 4 | `213e184` | `docs/api/messages.md` and 11 pinning tests in `tests/test_documented_messages.py` |
| 5a | `50695ac` | fix: persist each cart item's delivery address; drop the dead checkout field |
| 5b | `4905c93` | `docs/README.md`, `docs/data-model.md`, `docs/sample-data.md`, `docs/api/examples.md`; README corrections |
| 6 | this commit | final gate, `schema.yml` regeneration, this record |

---

## What each task now does

### Task 1 — Adopted app tests

The nine `apps/*/tests_comprehensive.py` modules moved to `tests/test_*_comprehensive.py`, where
`pytest.ini` (`testpaths = tests`) actually collects them. The eight failures were repaired against
the P2/P3 model: fixtures now create the mandatory `Listing.store`, checkout assertions follow one
order per cart item plus a `CheckoutSession`, inquiry creation uses the assigned `sender`, and
listing-expiry assertions use the current `Listing.Status` values. Assertions that only pinned a
removed implementation detail were dropped; assertions that express a real invariant were kept.

Suite: 150 → **173 passed**.

### Task 2 — Offline-safe currency

`tests/conftest.py` gained an autouse `fixed_exchange_rates` fixture that seeds the
`harbour_hub_exchange_rates_usd` cache key before any serializer runs. A regression test serializes
money with the network layer patched to raise, proving no test can reach `open.er-api.com`. The
fixed rates are documented in `docs/sample-data.md`.

`tests/test_currency.py` still patches `get_exchange_rates` directly, so the fixture does not hide
a missing-rate path.

Suite: **174 passed**.

### Task 3 — Schema metadata and generated endpoint reference

`SPECTACULAR_SETTINGS` now carries a description for every tag, plus `CONTACT`, `LICENSE`,
`SERVERS`, and a multi-paragraph `DESCRIPTION` covering auth, money, pagination, and the error
envelope.

`scripts/generate_api_reference.py` reads `schema.yml` and emits a deterministic Markdown table per
tag with method, path, operation id, summary, auth, and success codes. `docs/api/endpoints.md` is
generated from it and must not be hand-edited. `docs/api/README.md` covers base URLs, versioning,
JWT auth and session removal, roles, pagination, filtering, error shapes, rate limits, money rules,
status enums, the webhook contract, and regeneration steps.

Schema: 192 paths, 259 operations, 0 warnings, 0 errors.

### Task 4 — Message catalogue

`docs/api/messages.md` catalogues every success and error string with its status code, JSON shape,
and trigger, across auth/OTP/2FA, onboarding, listings, stores, cart, checkout/payment,
orders/rentals, quotes, disputes, reviews, messaging/inquiries, notifications, financials/payouts,
admin, compliance, support, and search.

`tests/test_documented_messages.py` pins 11 high-value strings by hitting the real endpoints:
privileged registration, storeless listing creation, empty cart, foreign cart ids, invalid webhook
signature, notification isolation, payout over balance, self-review, duplicate review, self-inquiry,
and cancelling a cancelled order.

Fact-checking the catalogue corrected four claims: the dispute resolve/refund success strings, the
retry-payment status (`400`, not `200`), the session `remove-all` verb (`DELETE`), and the exact
webhook success and duplicate bodies.

Suite: **185 passed**.

### Task 5 — Data model, sample data, and worked examples

- `docs/data-model.md` — domain map, every entity, 20 invariants, status machines for `Order`,
  `Payment`, `VendorEarning`, `Payout`, `Refund`, `QuoteRequest`, `Dispute`, and `RentalExtension`,
  constraints and indexes, a worked money example, and code references.
- `docs/sample-data.md` — the `SEED_SAMPLE_DATA` / `--force` gate, `--clean` safety, determinism,
  created entities and counts, seeded accounts, money invariants, idempotency, verification
  queries, fixed test rates, and what the command deliberately does not create.
- `docs/api/examples.md` — auth, seller onboarding, listings, cart, checkout, webhook, verify,
  order, earning, fulfilment, rental extension, quotes, disputes, refunds, bank accounts, payouts,
  transfers, notifications, and cross-cutting errors, each with request, success body, and common
  failures.
- `docs/README.md` — the repository documentation index, source-of-truth table, and full gate.
- The root `README.md` now has correct API paths, correct sample-data commands, pytest commands,
  and links to the docs.

Fact-checking the examples found a real bug: `CartItemCreateSerializer.create()` dropped
`delivery_detail`, so the address a buyer picked was never persisted on the cart item or copied to
the order. It is fixed in `50695ac` with two regression tests.

Suite: **187 passed**.

### Task 6 — Final gate

`schema.yml` was regenerated and validated; `docs/api/endpoints.md` regenerates with no diff. All
five gates pass. This record is the last commit of the phase.

---

## Documentation index

| Document | Contents |
|---|---|
| `docs/README.md` | Index, reading order, source-of-truth table, maintenance steps, full gate. |
| `docs/api/README.md` | Base URLs, auth, roles, pagination, errors, rate limits, money, enums, webhooks. |
| `docs/api/endpoints.md` | Generated reference for 259 operations across 192 paths. |
| `docs/api/messages.md` | Exact success and error strings with status codes and triggers. |
| `docs/api/examples.md` | Worked end-to-end request/response flows. |
| `docs/data-model.md` | Entities, invariants, status machines, constraints, worked money example. |
| `docs/sample-data.md` | The deterministic sample dataset and safe seeding. |

---

## Deviations from the plan

1. **Task 5 also contains a bug-fix commit.** Writing the worked examples exposed the dropped
   `delivery_detail`; the fix is committed separately (`50695ac`) so the docs commit stays
   documentation-only.
2. **`create_sample_data` does not print credentials.** The plan said it did; the code does not.
   The accounts are documented from the command's own values (`admin` / `password123`,
   `user_N@sample.harbourhub.com` / `password123`) instead of inventing output.
3. **The plan's `hb/settings_test.py` change was unnecessary.** The deterministic rates live in the
   autouse `tests/conftest.py` fixture, which is the only place tests read them.
4. **Unreachable enum values are documented, not wired up.** `Dispute.Status.REFUNDED` and
   `CANCELLED`, and `VendorEarning.Status.PROCESSING`, are defined but never set. Changing that is
   a behaviour change, so P4 records it as debt.
5. **The quote `decline` message bug is documented, not fixed.** `QuoteRequestActionView` builds
   `f"Quote {action}ed successfully"`, so declining returns `Quote declineed successfully`. Fixing
   it would change a pinned client-facing string; it is recorded as debt.
6. **The examples assume `preferred_currency: "NGN"`.** `CurrencyConverterMixin` displays USD by
   default, so the documents state the preference up front; otherwise the numbers would not match
   the stored NGN values.

---

## Verification commands

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python -m pytest -q
python -m flake8 apps hb tests --select=F401,F821,F841 --exclude=migrations
python manage.py spectacular --file schema.yml
python manage.py spectacular --file schema.yml --validate
python scripts/generate_api_reference.py
```

Latest output summary:

```
System check identified no issues (0 silenced).
No changes detected
187 passed, 2 warnings in 36.70s
(flake8: clean, exit 0)
(schema: exit 0, 0 errors, 0 warnings)
wrote docs\api\endpoints.md (259 operations) — no diff
```

---

## Still requires staging

These were carried forward from `P0-COMPLETE.md` through `P3-COMPLETE.md` and still cannot be
proven locally:

| Item | Why it cannot be proven locally |
|---|---|
| P0 manual acceptance (10 checks) | needs real accounts and a live Paystack test key |
| A real Paystack rental-extension payment → webhook → `apply_rental_extension` | needs a live test key and a real charge |
| A real refund request → webhook → `finalize_refund` | needs a live test key and a real transfer |
| A real transfer success/failure (`process_payout_task`) | needs a live recipient and bank |
| Termii or Twilio SMS delivery | needs provider credentials and a real phone number |
| A real web push | needs VAPID keys and a browser subscription |
| Scheduled tranche release via Celery Beat | verified eagerly in tests; scheduling belongs to the deployed worker |
| Production-volume admin payments | verified against small datasets only |

---

## Remaining known debt (post-P4)

1. **Staging-only verification.** The table above cannot be closed from this repository.
2. **`Dispute.Status.REFUNDED` and `CANCELLED` are never set.** A refund leaves the dispute in
   `under_review`; the enum values exist but no code path writes them.
3. **`VendorEarning.Status.PROCESSING` is never entered.** Earnings move `pending` →
   `partially_released` → `available` → `paid_out`, or `reversed`.
4. **Checkout writes `delivery_fee = 0.00` for every order.** The field, the commission rule, and
   the seeded dataset all support a delivery fee, but the checkout view does not compute one.
5. **`Quote decline` returns `Quote declineed successfully`.** The message is built with string
   concatenation; the double `e` is a wording bug, pinned in `docs/api/messages.md`.
6. **`EarningsSummaryView` does not match its declared schema.** The response returns
   `total_revenue`, `pending_balance`, `available_balance`, `total_withdrawn`,
   `revenue_change_percent`, and `currency`; `docs/api/examples.md` documents the real body.
7. **`AdminActionLog` pagination is unordered.** It raises `UnorderedObjectListWarning`; add a
   deterministic ordering to the model or the view.
8. **Notification preferences and delivery attempts have no HTTP surface.**
   `NotificationPreference` and `NotificationDelivery` are internal; only in-app notification CRUD
   is exposed. Documented rather than changed.
9. **The `reportlab` deprecation warnings** come from the installed package and will disappear with
   a dependency bump; they are not project code.

---

## Out of scope for P4

Advertisements, premium users, social login, and realtime chat are not part of the connectivity
spec. They need their own plan.
