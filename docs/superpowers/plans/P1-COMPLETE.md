# Harbour Hub P1 — Completion Record

> **Plan:** `docs/superpowers/plans/2026-10-26-harbour-hub-p1-500s-and-dead-features.md` (committed `9be0b53`).
> **Spec:** `docs/superpowers/specs/2026-10-26-harbour-hub-connectivity-design.md` §2.2, Phase P1.
> **Branch:** `main`.

---

## Result

Every S1 defect (D-15 … D-30, D-32) is fixed and covered by a test. The suite is green at
**85 passed**, with no pending migrations and a schema that validates with zero errors.

| Gate | Result |
|---|---|
| `python manage.py check` | no issues |
| `python manage.py makemigrations --check --dry-run` | no changes |
| `python -m pytest -q` | 85 passed, 2 warnings |
| `python -m flake8 apps hb --select=F821 --exclude=migrations` | clean |
| `python manage.py spectacular --file schema.yml --validate` | 0 errors, 4 operation-id warnings |

The 4 warnings are duplicate `operationId`s on the cart and order-cancel routes. They are
cosmetic (spectacular resolves them with numeric suffixes) and belong to the P3 API-cleanup pass.

---

## Commits

| Task | Commit | What changed |
|---|---|---|
| Plan | `9be0b53` | P1 plan |
| 1 | `b952ace` | rental reminders read `OrderItem` dates (D-15) |
| 2 | `d14850e` | analytics caches the serialised overview (D-16) |
| 3 | `beb17d9` | admin payments/stats stop traversing the missing `Payment.order` (D-17, D-18) |
| 4 | `d6b28b2` | listing visibility, delete guard, publish/pause/resume guard (D-19…D-21) |
| 5 | `f5551d6` | extend-rental on items; ship requires tracking and dispatches (D-22, D-23) |
| 6 | `8b3481f` | integer `order_id`, totals on list and tracking (D-24, D-25) |
| 7 | `0e8bee8` | seller timeline access; paid cancellation via refund (D-27, D-28) |
| 8 | `fded291` | review CRUD and paid-order gate (D-26) |
| 9 | `a4c093c` | sale counts across the paid lifecycle (D-29) |
| 10 | `1c70dc1` | single schema file, validated in CI (D-30) |
| 11 | `92587e4` | debug print replaced with logging (D-32) |
| 12 | `baac05e` | every GET route smoke-tested for 500s |
| 13 | `bf6ba63` | hire lifecycle reachable end to end (exit criteria) |

---

## What each fix now does

### D-15 — Rental reminders

`send_rental_reminders_task` filters `OrderItem` by `purchase_type` and `rental_end_date`,
joined to `Order` only for status. Active rental statuses are `paid` through `active_hire`;
`fulfilled`, `cancelled` and the terminal states are excluded. One notification per order even
when several hire items share an end date.

### D-16 — Analytics cache

The view serialises the payload *before* `cache.set`, so a cached response is already a plain
JSON-safe dict. The cache check is `is not None`, so a valid empty payload is still cached.
Repeated calls now return byte-identical payloads.

### D-17 / D-18 — Admin payments

* The list view selects `buyer` and `checkout_session`, prefetches
  `checkout_session__orders`, and searches `reference` and `buyer__email`.
* Platform revenue is `VendorEarning.commission_amount`, not `Order.escrow_fee` (which is
  permanently zero now that buyers pay no fee).

### D-19 / D-20 / D-21 — Listings

* Public filters use `Q(store__is_active=True) | Q(store__isnull=True)`, so the join can never
  hide a row.
* The delete guard uses `LIVE_ORDER_STATUSES` from `apps/commerce/constants.py`.
* Publish/pause/resume only write store activity when a store exists.

### D-22 / D-23 — Rental extension and shipping

* Extend-rental updates every hire/lease `OrderItem`, returns the legacy
  `message` / `new_end_date` / `rental_days_total` shape, and 400s for non-rental orders or
  shorter dates.
* Ship requires `carrier` and `tracking_id`, moves `paid|order_confirmed → item_dispatched`,
  stores both values, and writes a `shipped` activity with the tracking details.

### D-24 / D-25 — Order contracts

* `order_id` is an integer (`source="id"`); `order_number` is display-only.
* The list returns `total_amount`; the tracking page returns
  `total_amount`, `subtotal`, `delivery_fee`, `escrow_fee`.
* Both read the listing title through `items`, so the P2 grain change will not break them.

### D-26 — Reviews

* Editing and deleting are available at `/reviews/listings/<id>/` and `/reviews/stores/<id>/`.
* Creation requires an `OrderItem` in a paid lifecycle state; a store review additionally
  requires that the item belongs to that store.
* Only the reviewer may edit or delete.

### D-27 / D-28 — Timeline and cancellation

* Buyer, seller, store owner and staff can read `/orders/<id>/activity/`.
* `POST /orders/<id>/cancel/` cancels unpaid orders immediately. For a `paid` order it creates a
  full refund through `request_refund` and returns `202`; `finalize_refund` (webhook-driven)
  owns the `cancelled` transition.

### D-29 — Sales counts

`SALES_STATUSES` in `apps/commerce/constants.py` is the single source of truth used by
`Store.sales_count`, `RecentSalesView`, `PublicRecentSalesView`, analytics revenue and the review
gate. It covers every paid state from `paid` to `fulfilled`.

### D-30 / D-32 — Schema and logs

* `schema.yaml` (zero bytes) is deleted; `schema.yml` is regenerated and validated in CI.
* `RetryPaymentView` declares `request=None`, removing the last schema error.
* The `print` in `apps/listings/tasks.py` is now `logger.info`. The `listings/serializers.py`
  print named by the spec was already removed in P0. Two prints remain in
  `apps/commerce/tests_comprehensive.py`; that module is test code, not production.

### Exit criteria — hire lifecycle

`OrderTrackingUpdateView` now allows `hire_started` and `hire_ended`. A hire order runs
`delivered → active_hire → hire_ended → item_returned → fulfilled`; a buy order still runs
`delivered → fulfilled`. Unauthorised callers get `403`, invalid transitions `400`.

---

## Route smoke coverage

`tests/test_route_smoke.py` walks the resolver, materialises every path parameter, issues an
authenticated `GET`, and fails on any `5xx`. It asserts that more than 50 routes were probed and
that `/listings/` and `/commerce/orders/` were among them, so the test cannot pass vacuously.
Skipped prefixes are HTML admin, schema/docs, the payment gateway endpoints, checkout, and
logout.

Mutation endpoints are covered individually by Tasks 1–9 and the lifecycle tests.

---

## Deviations from the plan

1. **`apps/commerce/constants.py` was created in Task 1**, not Task 9. The reminder task and the
   delete guard need the same status lists, and creating it early avoided a broken intermediate
   commit. Task 9 then replaced the remaining literals.
2. **D-19 is structurally resolved by P0.** `Listing.store` is non-null and `PROTECT`, so a
   store-less listing cannot exist. The OR guard is retained as defence in depth; the tests
   cover the reachable behaviour instead (active store visible, inactive store hidden).
3. **The paid cancellation path does not set `Order.status = CANCELLED`.** The refund webhook
   (`finalize_refund`) owns that transition and also reverses the vendor earning. Setting it
   early would let a failed refund leave a cancelled order with captured money.
4. **`AdminProfile` has no `modules` field** as the drafted test assumed; that test uses a
   superuser, which short-circuits the `RolePermission` matrix. Module-level permission coverage
   already exists in `tests/test_admin_permissions.py`.
5. **`schema.yml` changed by ~10 KB** because P1 added review detail endpoints and new
   serializer fields.
6. **A hire order cannot be fulfilled directly from `delivered`.** The state machine requires
   the rental states first. This is deliberate; the previous map silently allowed completing a
   rental without ever activating it.

---

## Still requires staging

| Item | Why it cannot be proven locally |
|---|---|
| Paystack refund request → webhook → `finalize_refund` | needs a live test key and a real transfer |
| Rental reminder at 08:00 via beat | verified eagerly in tests; scheduling belongs to the deployed worker |
| Admin payments page with production volume | verified against empty and one-row datasets only |
| Currency-converted tracking amounts | unit tests pin `hh-currency: NGN` to avoid network calls |
| P0 manual acceptance checklist | unchanged; see `P0-COMPLETE.md` |

### Local test caveat

`apps/core/currency.py` fetches `open.er-api.com` when a converted response is requested. Tests
that assert converted amounts send `HTTP_HH_CURRENCY="NGN"` so conversion is a no-op. Any new
test that renders a `CurrencyConverterMixin` serializer should do the same, or the suite will
make a real HTTP call.

---

## P2 hand-off

P1 fixed the *shape* of the order APIs. P2 must now fix the *grain and the money*:

1. One cart item → one `Order`; remove the store-less grouping in `CheckoutView`.
2. Store is the authoritative vendor; drop reliance on `items[0].listing.user`.
3. Snapshot commission rate and currency rate on the order at checkout.
4. 50/50 tranches for hire orders, built on `released_amount` / `paid_out_amount`.
5. `RentalExtension` as a payable object, not a free date mutation.
6. Notification dispatcher: in-app, email, SMS, push, staff webhook, with a delivery ledger.
7. `release_pending_earnings_task` null-order guard and `process_payout_task` idempotency.
8. N+1 sweep on the list endpoints (`select_related`/`prefetch_related`).
9. Ad-hoc root scripts (`test_paystack*.py`, `test_posthog.py`, `test_recent_sales.py`) removed
   or converted to real tests.
