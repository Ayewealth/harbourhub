# Harbour Hub P2 — Completion Record

> **Plan:** `docs/superpowers/plans/2026-10-26-harbour-hub-p2-order-model-and-money.md` (committed `f70ab48`).
> **Spec:** `docs/superpowers/specs/2026-10-26-harbour-hub-connectivity-design.md` §2.2, Phase P2.
> **Branch:** `main`.

---

## Result

The order grain is now one cart item = one `Order`, the store is the authoritative vendor, money is
Decimal and NGN at rest with snapshotted commission and currency, earnings release in two tranches,
payouts allocate per store and per earning, rental extensions are payable objects, refunds reverse
proportionally, and every notification event is dispatched to every configured channel.

The suite is green at **138 passed**, with no pending migrations and a schema that validates with
zero errors.

| Gate | Result |
|---|---|
| `python manage.py check` | no issues |
| `python manage.py makemigrations --check --dry-run` | no changes |
| `python -m pytest -q` | 138 passed, 2 warnings |
| `python -m flake8 apps hb --select=F821 --exclude=migrations` | clean |
| `python manage.py spectacular --file schema.yml --validate` | 0 errors, 4 operation-id warnings |

The 4 warnings are the same duplicate `operationId`s P1 recorded on the cart and order-cancel
routes. They are cosmetic and belong to the P3 API-cleanup pass.

---

## Commits

| Task | Commit | What changed |
|---|---|---|
| Plan | `f70ab48` | P2 plan |
| 1 | `ed19627` | Decimal-native `money`, `convert_to_ngn`, `convert_from_ngn`; `CurrencyRateUnavailable` |
| 2 | `64ae89c` | `Order.store` mandatory (`PROTECT`), commission snapshot and lifecycle timestamps, `OrderItem` currency snapshot |
| — | `efad1e9` | schema regenerated for the mandatory order store |
| 3 | `b84555c` | one order per cart item; store-derived seller; zero buyer fees; currency converted once and snapshotted; 502 keeps the cart |
| 4 | `f6555da` | `finalize_payment` snapshots commission on goods only; `accrue_earning` snapshot-driven; platform revenue = sum of commissions |
| 5 | `bca9165` | single `transition()` lifecycle service; confirm-receipt endpoint; fulfilment releases the final tranche |
| 6 | `fcb4243` | `ReleasePolicy`, `first_release_at`, `final_release_at`; 50/50 release task with `skip_locked`; `payout` FK removed |
| 7 | `05de923` | one wallet per store; `Payout.store` mandatory; `PayoutAllocation` is the only earning↔payout link |
| 8 | `d8e488d` | `RentalExtension`; per-item paid extend-rental endpoint; legacy endpoint returns `400` with the item endpoint |
| 9 | `806a05b` | `reverse_earning_amount`; partial refunds keep the order and reverse proportionally; full refund cancels and reverses |
| 10 | `b161ce1` | preferences, delivery ledger, channel adapters, dispatcher, `deliver_notification_task` |
| 11 | this commit | `tests/test_p2_exit_criteria.py` and this record |

---

## What each task now does

### Task 1 — Decimal money and currency

`apps/financials/services.py::money` quantises half-up to two decimals and is the only rounding
function used on money. `apps/core/currency.py` exposes `convert_to_ngn` / `convert_from_ngn`
returning `Decimal`, and raises `CurrencyRateUnavailable` when a rate is missing. No float math
remains on a money path.

### Task 2 — Order model

* `Order.store` is non-null with `on_delete=PROTECT`; `Order.seller` is derived from `store.user`.
* `Order` carries `commission_rate`, `commission_amount`, `shipped_at`, `delivered_at`,
  `completed_at`, `cancelled_at`, `cancellation_reason`.
* `OrderItem` carries `original_currency`, `original_unit_price`, `exchange_rate`.
* Migration `commerce.0012_order_p2_fields` is guarded: it backfills `store` from the first item's
  listing and refuses to proceed if an order has no resolvable store. `backfill_order_stores`
  exists for a staged dry run.

### Task 3 — Checkout

One `CartItem` becomes one `Order` with one `OrderItem`; quantity stays on that item. A cart with
three items from three stores produces three orders, and three items from one store also produce
three orders. The buyer pays `subtotal + delivery_fee`; `escrow_fee` is always zero. Foreign
prices are converted once, and the rate is snapshotted on the item. A Paystack initialization
failure returns `502` and leaves the cart untouched.

### Task 4 — Commission

Commission is charged on goods only: `commission = money(subtotal * rate / 100)`; delivery passes
through in full. `finalize_payment` snapshots the store's current rate on the order and computes
the commission; `accrue_earning` reads that snapshot rather than the live store rate, so a later
rate change never rewrites history. The admin platform revenue is the sum of
`Order.commission_amount`, which equals the sum of `VendorEarning.commission_amount`.

`VendorEarning.save()` no longer auto-calculates commission or net; both are explicit writes.

### Task 5 — Lifecycle

`apps/commerce/services/orders.py::transition` is the only function allowed to change
`Order.status`. It enforces the transition table, writes the `OrderActivity`, and stamps the
matching timestamp. `item_dispatched` is allowed from `paid` or `order_confirmed` and requires
carrier and tracking ID. A hire order fulfils only from `item_returned`; a buy order fulfils from
`delivered`. Unpaid cancellation (`draft`/`pending_payment`) goes through the service; a paid
cancellation still goes through a refund.

`POST /commerce/orders/<id>/confirm-receipt/` is buyer-only, fulfils the order, sets
`completed_at`, and releases the final tranche.

### Task 6 — Tranche release

`VendorEarning` gains `release_policy` (`split_50_50` default, `full`), `first_release_at`,
`final_release_at`; the legacy `payout` FK is removed. `release_pending_earnings_task` selects
candidates with `select_for_update(skip_locked=True)`, releases half the net amount at day 7, and
releases the remainder when `final_release_at` is stamped by fulfilment. The task is idempotent:
a second run finds nothing left to release. Disputed earnings are frozen.

### Task 7 — Wallets and payouts

One `VendorWallet` per `Store` (`store` non-null, `user` derived). `Payout.store` is mandatory and
`PROTECT`ed. `VendorEarning.payout` is replaced by `PayoutAllocation`, so a payout can settle part
of one earning while the rest stays held. `settle_payout` advances only the allocations attached to
that payout; `fail_payout` reverses only those allocations and re-credits the reserved amount.
Payout freezing is payout-level only and no longer rewrites earning statuses.

Migration `financials.0008_wallet_store_and_payout_store` attaches legacy store-less wallets to
their owner's store, creates any missing wallet, and refuses to proceed with unresolved rows.

### Task 8 — Paid rental extensions

`RentalExtension` records the item, additional days, previous/new end date, amount, currency, and
the payment that settles it. `POST /commerce/orders/<id>/items/<item_id>/extend-rental/` creates a
pending extension and a Paystack payment; the item's dates do not move until
`finalize_payment` confirms the payment, which then applies the extension exactly once.

The extension amount is added to the order subtotal and total, the earning gross and net grow, and
the extra net is credited to the store wallet. Commission on the extension uses the earning's
snapshot rate.

`POST /commerce/orders/<id>/extend-rental/` is retained as a legacy redirect: it returns `400`
with the `item_id` and the correct item endpoint.

### Task 9 — Refunds

`reverse_earning_amount(earning, amount, reason)` reverses a proportional slice of net earnings,
taking held funds (`pending_balance`) first and released funds (`available_balance`) second, and
writes one `WalletTransaction` ledger row. A full refund reverses the whole earning, cancels the
order with a timestamp and reason, and writes an `order_refunded` activity. A partial refund
reverses `net_amount * refund/payment` and leaves the order in place.

`finalize_refund` is idempotent: a second call sees `processed` and returns.

### Task 10 — Notifications

* `NotificationPreference` stores per-user, per-category opt-in for in-app, email, SMS, and push.
* `NotificationDelivery` is the ledger: one row per channel attempt with status, provider ID,
  error, and attempts.
* `channels.py` holds the only provider calls: email (Django mail), SMS (Termii or Twilio), push
  (skips until a subscription exists), and the staff webhook.
* `services.py` decides the channels per event and queues deliveries; it never sends.
* `deliver_notification_task` sends one delivery, marks it sent/failed/skipped, and retries a
  transient failure without affecting other channels.
* `create_notification` still writes the in-app row and now queues the out-of-band channels. Any
  dispatcher error is swallowed so the business action cannot fail because a broker is down.

---

## Deviations from the plan

1. **`NotificationDelivery.Status.SKIPPED` is an addition** to the spec's three statuses. Without
   it, an adapter with no credentials would have to report `sent`, which would be a lie. The
   ledger now records why nothing was sent (`SMS provider is not configured`, `Push is not
   configured`, `Recipient opted out`).
2. **Commission is charged on goods only.** `gross = subtotal + delivery`, but
   `commission = money(subtotal * rate/100)`. The plan's `VendorEarning` table described
   `commission_amount` as `round(gross_goods * rate/100)`; this record makes explicit that
   "goods" excludes delivery, matching the spec's pass-through rule.
3. **The legacy extend-rental endpoint returns `400`, not `200`.** Free date mutation is gone; the
   response carries `item_id` and the correct item endpoint so a client can migrate.
4. **A rental extension does not reset `first_release_at`.** If the first tranche was already
   released, the extra net is held until `final_release_at = now + 7 days`; if it was not, the
   extra net simply joins the existing schedule. Resetting the first tranche would strand the
   already-released amount.
5. **A partial refund takes held funds before released funds.** The plan's prose implied the
   reverse; taking from `pending_balance` first avoids clawing back money the vendor could already
   have withdrawn, and the tests pin that behaviour.
6. **`reverse_earning` is kept** even though `finalize_refund` now calls
   `reverse_earning_amount`; it remains the whole-earning reversal primitive for future
   admin/dispute paths.
7. **Migration ordering.** `commerce.0012` (mandatory store) landed before `financials.0007`
   (tranche fields) and `financials.0008` (wallet/payout store) because the financials backfills
   read `Order.store` and `Store.user`. The local `harbour_hub` database applied all three
   successfully without data loss.
8. **The P2 schema commit `efad1e9` is separate** from Task 4's code commit because the
   `Order.store` change was generated by Task 2 but committed after Task 3's tests.

---

## Verification commands

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python -m pytest -q
python -m flake8 apps hb --select=F821 --exclude=migrations
python manage.py spectacular --file schema.yml --validate
```

Latest output summary:

```
System check identified no issues (0 silenced).
No changes detected
138 passed, 2 warnings in 28.61s
(flake8: clean)
Schema generation summary: Warnings: 4 (4 unique)  Errors: 0 (0 unique)
```

`tests/test_p2_exit_criteria.py` is the single executable summary: one order per cart item across
and within stores, no buyer fee, platform revenue = sum of commissions, two-tranche release,
payout of the first tranche only, extension dates only after payment, and a full refund that
zeroes the store wallet.

---

## Still requires staging

| Item | Why it cannot be proven locally |
|---|---|
| A real Paystack rental-extension payment → webhook → `apply_rental_extension` | needs a live test key and a real charge |
| A real refund request → webhook → `finalize_refund` | needs a live test key and a real transfer |
| A real transfer success/failure (`process_payout_task`) | needs a live recipient and bank |
| Termii or Twilio SMS delivery | needs provider credentials and a real phone number |
| A real web push | needs VAPID keys and a browser subscription |
| Scheduled tranche release via Celery Beat | verified eagerly in tests; scheduling belongs to the deployed worker |
| Production-volume admin payments | verified against small datasets only |

---

## P3 hand-off

1. **N+1 sweep** on order, listing, store, and admin list endpoints (`select_related` /
   `prefetch_related`), measured with `django-debug-toolbar` or `assertNumQueries`.
2. **Indexes** for the hot filters: order status + placed_at, earning status + first_release_at,
   notification recipient + created_at.
3. **Root scripts**: remove or convert `test_paystack*.py`, `test_posthog.py`,
   `test_recent_sales.py`.
4. **Idempotent seeding** behind `SEED_SAMPLE_DATA=true`; never seed by default.
5. **`F401` / `F841` cleanup** across `apps` and `hb`, then widen the CI flake8 gate.
6. **Operation-id cleanup** for the four cart/order collisions, then make schema warnings fail CI.
7. **Delete remaining stubs** and dead modules found by the audit.
