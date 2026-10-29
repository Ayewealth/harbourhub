# Harbour Hub P3 — Performance and Cleanup

> **Spec:** `docs/superpowers/specs/2026-10-26-harbour-hub-connectivity-design.md` §2.2, Phase P3.
> **Predecessors:** `P0-COMPLETE.md`, `P1-COMPLETE.md`, `P2-COMPLETE.md`.
> **Branch:** `main`.

## Goal

P0–P2 made every reachable path correct and the money model sound. P3 removes the drag and the
noise: dead scripts, empty test modules, unused imports, N+1 queries on the list endpoints, missing
hot-path indexes, sample data that writes invalid money, and the four schema operation-id
collisions. No behaviour change is intended; every task must leave the suite green.

**Hard rules carried forward**

- Never delete or rewrite live data. Migrations are additive and guarded.
- One task, one commit. Run the full gate before each commit.
- Do not widen the CI flake8 gate until the tree is clean under the wider selection.
- `python -m flake8` (flake8 is not on `PATH`).

## Baseline (at `8964f5d`)

| Metric | Value |
|---|---|
| `pytest` | 138 passed |
| `flake8 --select=F401,F841` | 82 F401 + 8 F841 |
| Root scripts | `test_paystack.py`, `test_paystack2.py`, `test_posthog.py`, `test_recent_sales.py` |
| Empty `apps/*/tests.py` stubs | 12 |
| Schema warnings | 4 operation-id collisions |

---

## Task 1 — Remove root scripts and empty test stubs

**Why:** four ad-hoc root scripts hit live Paystack/PostHog when run and are collected by nothing.
Twelve `apps/*/tests.py` modules contain only `from django.test import TestCase` and a comment.

**Files**

- Delete: `test_paystack.py`, `test_paystack2.py`, `test_posthog.py`, `test_recent_sales.py`
- Delete: `apps/{accounts,admin_panel,analytics,categories,compliance,core,financials,inquiries,listings,messaging,notifications,store,support}/tests.py`

**Steps**

1. Confirm nothing imports or references the scripts (`grep`).
2. Delete the files.
3. Run the full gate.

**Commit:** `chore: remove ad-hoc root scripts and empty test stubs`

---

## Task 2 — Unused import and variable cleanup

**Why:** the CI gate currently selects `F821` only. The tree has 82 unused imports and 8 unused
locals, which hide real mistakes and make review noisy.

**Files:** every file named by
`python -m flake8 apps hb --select=F401,F841 --exclude=migrations`.

**Steps**

1. Keep the two side-effect imports in `apps/financials/apps.py` and `apps/listings/apps.py`;
   mark them `# noqa: F401`.
2. Remove unused imports. Prefer deleting the whole line when the import is the only name.
3. Remove unused locals:
   - `apps/accounts/serializers.py` — `except Exception as e:` → `except Exception:`
   - `apps/accounts/views.py` — drop the unused `tf =` binding, keep the `DoesNotExist` guard
   - `apps/listings/views.py` — drop unused `instance` / `user`
   - `apps/compliance/views.py` — drop `expiry_warning_days`
   - `apps/core/management/commands/create_sample_data.py` — drop unused `stores` / `quotes`
4. Re-run `flake8 --select=F401,F841` until clean.
5. Widen CI: `flake8 apps hb --select=F401,F821,F841 --exclude=migrations`, update the comment.

**Tests:** full suite; no test should need a removed import.

**Commit:** `chore: remove unused imports and locals and widen the lint gate`

---

## Task 3 — Safe, idempotent sample data

**Why:** `create_sample_data` writes `VendorEarning` without commission/net, so every seeded
earning has `net_amount = 0` after P2 removed the auto-calculation. It also deletes everything
with `--clean` and can run by accident in production.

**Files**

- Modify: `apps/core/management/commands/create_sample_data.py`
- Create: `tests/test_sample_data.py`

**Steps**

1. Refuse to run unless `settings.SEED_SAMPLE_DATA` is true (`SEED_SAMPLE_DATA=true`), or
   `--force` is passed. Add `SEED_SAMPLE_DATA = config("SEED_SAMPLE_DATA", default=False,
   cast=bool)` to `hb/settings.py`.
2. Make `--clean` require `--force` as well.
3. Write P2-correct money on every seeded order:
   - `Order.subtotal`, `delivery_fee`, `total_amount`, `commission_rate`,
     `commission_amount`;
   - `OrderItem.original_currency`, `original_unit_price`, `exchange_rate`;
   - `VendorEarning.gross_amount`, `commission_rate`, `commission_amount`, `net_amount`,
     `release_policy`, `first_release_at`.
4. Make repeated runs idempotent: natural-key `get_or_create` for categories, stores, listings,
   orders (by `order_number`), earnings (by `order`), and notifications (skip if any exist).
5. `tests/test_sample_data.py`: the command refuses without the setting; a run with the setting
   produces orders whose `total_amount == subtotal + delivery_fee` and earnings whose
   `net_amount == gross_amount - commission_amount`; a second run adds no duplicates.

**Commit:** `feat(core): gate and repair sample data seeding`

---

## Task 4 — N+1 sweep on the hot list endpoints

**Why:** the order, quote, dispute, and recent-sales lists serialise related rows without
`select_related` / `prefetch_related`.

**Files**

- Modify: `apps/commerce/views.py`
- Create: `tests/test_query_counts.py`

**Steps**

1. Add the missing relations:
   - `OrderListCreateView`: `prefetch_related("items__listing")`
   - `BuyerSentQuotesView`, `SellerReceivedQuotesView`: `select_related("listing", "buyer",
     "store", "listing__store")`
   - `DisputeListCreateView` / `DisputeDetailView`: `select_related("buyer", "order",
     "order__store")`
   - `RecentSalesView`: `select_related("buyer", "store")` + `prefetch_related("items__listing")`
2. `tests/test_query_counts.py` uses `django_assert_num_queries`-style counting with
   `CaptureQueriesContext`: create 5 rows, request the list, assert the query count does not grow
   with the number of rows (compare 1 row vs 5 rows, or assert a fixed ceiling).
3. Keep the assertions tolerant (a small constant), because pagination and auth add queries.

**Commit:** `perf(commerce): eager-load list relations to remove N+1 queries`

---

## Task 5 — Hot-path indexes

**Why:** the tranche task filters `status + first_release_at`; the order lists filter
`seller/store + status + created_at`; the delivery task filters `status + channel`.

**Files**

- Modify: `apps/commerce/models.py`, `apps/financials/models.py`,
  `apps/notifications/models.py`
- Migration: `commerce/00XX_p3_indexes.py`, `financials/00XX_p3_indexes.py`,
  `notifications/00XX_p3_indexes.py`

**Steps**

1. Add:
   - `Order`: `Index(fields=["store", "status", "-created_at"])`,
     `Index(fields=["seller", "status", "-created_at"])`,
     `Index(fields=["buyer", "-created_at"])`
   - `OrderItem`: `Index(fields=["order", "purchase_type"])`
   - `VendorEarning`: `Index(fields=["status", "first_release_at"])`,
     `Index(fields=["store", "status"])`
   - `NotificationDelivery`: `Index(fields=["status", "channel"])`
2. Generate migrations; confirm they only add indexes.
3. Apply to the local `harbour_hub` database.

**Commit:** `perf: index the hot order, earning, and delivery filters`

---

## Task 6 — Schema operation ids, final gate, completion record

**Why:** the four duplicate `operationId`s are the only remaining schema warnings, and P3 needs a
written record.

**Files**

- Modify: `apps/commerce/views.py` (cart item add/detail, order cancel)
- Create: `docs/superpowers/plans/P3-COMPLETE.md`
- Regenerate: `schema.yml`

**Steps**

1. Give the colliding views explicit `operation_id`s via `@extend_schema`:
   - cart add → `commerce_cart_item_add`
   - cart detail → `commerce_cart_item_detail`
   - order cancel → `commerce_order_cancel`
2. Regenerate the schema; expect `Warnings: 0`.
3. Run the full gate.
4. Write `P3-COMPLETE.md` with the commit table, final counts, and the remaining staging list.

**Commit:** `docs: record P3 completion and verification`

---

## Verification checklist

- [ ] `python manage.py check` clean
- [ ] `python manage.py makemigrations --check --dry-run` clean
- [ ] `python -m pytest -q` green
- [ ] `python -m flake8 apps hb --select=F401,F821,F841 --exclude=migrations` clean
- [ ] `python manage.py spectacular --file schema.yml --validate` 0 errors, 0 warnings
- [ ] No data deleted, no migration faked, no table dropped
- [ ] Every task committed separately
