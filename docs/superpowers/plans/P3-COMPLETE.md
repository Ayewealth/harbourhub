# Harbour Hub P3 — Completion Record

> **Plan:** `docs/superpowers/plans/2026-10-29-harbour-hub-p3-performance-and-cleanup.md` (committed `f70c704`).
> **Spec:** `docs/superpowers/specs/2026-10-26-harbour-hub-connectivity-design.md` §2.2, Phase P3.
> **Branch:** `main`.

---

## Result

P3 removed the drag and the noise without changing behaviour: the ad-hoc root scripts and empty
test stubs are gone, the tree is clean under the widened `F401/F821/F841` gate, sample data is
gated and idempotent, the hot list endpoints no longer N+1, the hot filters are indexed, and the
OpenAPI schema validates with zero warnings.

The suite is green at **150 passed**, with no pending migrations and a schema that validates with
zero errors and zero operation-id collisions.

| Gate | Result |
|---|---|
| `python manage.py check` | no issues |
| `python manage.py makemigrations --check --dry-run` | no changes |
| `python -m pytest -q` | 150 passed, 2 warnings |
| `python -m flake8 apps hb tests --select=F401,F821,F841 --exclude=migrations` | clean |
| `python manage.py spectacular --file schema.yml --validate` | 0 errors, 0 warnings |

The two remaining pytest warnings are the pre-existing `reportlab`/`ast.NameConstant`
`DeprecationWarning`s from a third-party package, not project code.

---

## Commits

| Task | Commit | What changed |
|---|---|---|
| Plan | `f70c704` | P3 plan |
| 1 | `4f4f713` | deleted 4 root scripts and 13 empty `apps/*/tests.py` stubs |
| 2 | `2a5eba5` | removed 82 `F401` + 8 `F841` findings; widened the CI lint gate |
| 3 | `d3521ab` | gated, P2-correct, idempotent `create_sample_data`; `tests/test_sample_data.py` |
| 4 | `bf52e9d` | eager loading on order/quote/dispute/recent-sales lists; `tests/test_query_counts.py` |
| 5 | `bbb203b` | composite indexes on `Order`, `OrderItem`, `VendorEarning`, `NotificationDelivery` |
| 6 | this commit | split cart collection/detail views, dedicated order-cancel view, schema and record |

---

## What each task now does

### Task 1 — Dead scripts and stubs

`test_paystack.py`, `test_paystack2.py`, `test_posthog.py`, and `test_recent_sales.py` are gone;
each hit a live gateway or analytics endpoint when run and was collected by nothing. Thirteen
`apps/*/tests.py` modules that only imported `TestCase` are gone. `apps/commerce/tests.py` was kept
because it contains real assertions.

### Task 2 — Lint gate

Every `F401` and `F841` finding in `apps`, `hb`, and `tests` is removed. The two side-effect signal
imports in `apps/financials/apps.py` and `apps/listings/apps.py` are kept with `# noqa: F401`.
CI now runs `flake8 apps hb --select=F401,F821,F841 --exclude=migrations`, so a new unused import
fails the build instead of accumulating.

### Task 3 — Safe sample data

`create_sample_data` refuses to run unless `SEED_SAMPLE_DATA=true` or `--force` is passed, and
`--clean` additionally requires `--force`. Seeded orders carry a consistent money model
(`total_amount == subtotal + delivery_fee`) and seeded earnings carry
`net_amount == gross_amount - commission_amount`. Rows are created by natural key and skipped when
they already exist, so a second run is a no-op. The command also creates a `Store` for every
seller **and** service provider, because `Listing.store` is mandatory since P2.

This task also fixed a latent `Order(order_type=...)` `TypeError` that had broken the command since
`commerce/0009`.

### Task 4 — N+1 sweep

`OrderListCreateView`, `BuyerMyOrdersListView`, `SellerStoreOrdersListView`, `RecentSalesView`,
the quote lists, and the dispute lists now load their relations eagerly. A shared
`order_list_prefetches()` helper keeps the order views consistent, and the primary listing image is
prefetched with `Prefetch(..., to_attr="primary_images")`; `get_primary_image` reads the prefetched
attribute before falling back to a query, so detail views still work. `tests/test_query_counts.py`
pins five list endpoints so the query count does not grow with the number of rows.

### Task 5 — Indexes

Additive migrations only:

- `commerce/0014_p3_indexes` — `Order(store, status, -created_at)`,
  `Order(seller, status, -created_at)`, `Order(buyer, -created_at)`,
  `OrderItem(order, purchase_type)`.
- `financials/0009_p3_indexes` — `VendorEarning(status, first_release_at)`,
  `VendorEarning(store, status)`.
- `notifications/0003_p3_indexes` — `NotificationDelivery(status, channel)`.

All three were applied to the local `harbour_hub` database without data loss.

### Task 6 — Schema operation ids

The cart collection and detail routes are now separate views, so each HTTP method has one URL and
one operation id:

- `POST /commerce/cart/items/` → `CartItemView` → `commerce_cart_item_add`
- `PATCH /commerce/cart/items/{item_id}/` → `CartItemDetailView` → `commerce_cart_item_update`
- `DELETE /commerce/cart/items/{item_id}/` → `CartItemDetailView` → `commerce_cart_item_remove`

`PATCH` or `DELETE` on the collection route now returns `405` instead of reaching a handler that
required an `item_id`.

`/commerce/orders/{id}/cancel/` is served by `OrderCancelView`, a thin subclass that keeps the
behaviour of `OrderDetailView.post` but declares `commerce_order_cancel`. The alias
`POST /commerce/orders/{id}/` keeps `commerce_orders_cancel_action_post`.

`tests/test_schema.py` now asserts that every `operationId` is unique, that the collection route
only accepts `POST`, that the detail route accepts `PATCH`/`DELETE`, and that a collection `PATCH`
returns `405`.

---

## Deviations from the plan

1. **The cart detail route has two operation ids, not one.** The plan sketched a single
   `commerce_cart_item_detail`; the implementation uses `commerce_cart_item_update` and
   `commerce_cart_item_remove` so generated clients get method-specific names. Both are unique,
   which is the actual requirement.
2. **The cancel route is a subclass, not an in-place override.** `OrderDetailView.post` is shared
   by two URLs, and drf-spectacular cannot give one method two operation ids. `OrderCancelView`
   reuses the implementation and only overrides the schema, so the cancel logic still lives in one
   place.
3. **Thirteen stubs were deleted, not twelve.** The plan listed twelve; the tree also had
   `apps/core/tests.py`, which was empty in the same way.
4. **The local lint gate includes `tests`; CI keeps the plan's `apps hb` selection.** The two
   `tests/` findings introduced by earlier work are fixed, and the wider local command is used
   during verification.
5. **`OrderListCreateView` prefetches more than `items__listing`.** It uses the shared
   `order_list_prefetches()` helper (items, listing, listing images, buyer/seller/store) so the
   serializer does not fall back to per-row queries.

---

## Verification commands

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python -m pytest -q
python -m flake8 apps hb tests --select=F401,F821,F841 --exclude=migrations
python manage.py spectacular --file schema.yml --validate
```

Latest output summary:

```
System check identified no issues (0 silenced).
No changes detected
150 passed, 2 warnings in 31.55s
(flake8: clean)
Schema generation summary: Warnings: 0 (0 unique)  Errors: 0 (0 unique)
```

---

## Still requires staging

These were already listed in `P0-COMPLETE.md` / `P2-COMPLETE.md` and cannot be proven locally:

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

## Remaining known debt (post-P3)

1. **`apps/*/tests_comprehensive.py` is never collected.** `pytest.ini` sets `testpaths = tests`,
   so those modules sit in the tree but never run. Decide whether to move the useful assertions
   into `tests/` or delete the modules; do not assume they are coverage.
2. **`CurrencyConverterMixin` can call `open.er-api.com` on a cold cache.** The suite relies on the
   cache after the first call. Pin the rate in tests or inject a fake converter so the suite is
   offline-safe.
3. **The two `reportlab` deprecation warnings** come from the installed package and will disappear
   with a dependency bump; they are not project code.
