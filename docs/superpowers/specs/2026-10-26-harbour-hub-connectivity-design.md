# Harbour Hub backend connectivity and correctness design

**Status:** Draft for review
**Date:** 2026-10-26
**Scope:** Every Django app in this repository (`accounts`, `admin_panel`, `analytics`, `categories`, `commerce`, `compliance`, `core`, `financials`, `health`, `inquiries`, `listings`, `messaging`, `notifications`, `reviews`, `settings`, `store`, `support`)
**Goal:** No endpoint, task, or function that is supposed to work is silently broken. Money, ownership, and permissions are correct end to end. Existing mock data is preserved and reconciled, never reset.

---

## 1. Why this document exists

The platform currently runs, but several core paths are quietly wrong:

- A buyer can pay and the vendor can end up with **no earning record at all**.
- A vendor can be **paid twice** because a payout never links to the earnings it settles.
- Any logged-in user can **refund any dispute**.
- Anyone can register as `super_admin`.
- A seller can **move a listing into another seller's store** by writing `store` in the request body.
- A verification document in the admin drawer resolves to `https://api.harbourhubglobal.com/media/sole_proprietorship` instead of a real file.
- A daily Celery task fails every morning, and the admin payments page cannot load.

These are not isolated typos. They accumulated because the app has **no test safety net, no CI gate, and a domain model that still assumes one order can contain many listings from many vendors**. This document fixes the model, the money, the permissions, and the safety net in that order.

### 1.1 Guiding invariants

Every implementation decision below must preserve these invariants:

1. **One cart item becomes one Order.** An Order has exactly one OrderItem. Quantity lives on that item. Orders are never combined across listings. An Order always has exactly one tracking ID.
2. **The Store is the vendor.** Ownership, commission, earnings, wallets, and payouts are keyed by Store. `Order.seller` is a denormalised pointer to `Store.user` for query convenience, never an independent source of truth.
3. **Buyers pay only the item subtotal plus delivery.** No escrow fee, no service fee, no platform fee on the buyer side.
4. **The platform earns commission from sellers only.** Commission is snapshot at checkout and booked as revenue when the order is paid.
5. **Money is Decimal, in NGN, at rest.** Foreign currencies are converted once at checkout and the rate is stored. Display conversion never mutates stored money.
6. **Payment success is confirmed by the Paystack webhook.** `GET /payment/verify/` is a read-only status poller. A reconciliation task may finalise a missed webhook, but it calls the same idempotent service.
7. **Every state change is authorised, explicit, and idempotent.**
8. **No destructive migration.** Add, backfill, verify, then constrain. Existing rows survive.

---

## 2. Current-state defect inventory

Severity: **S0** = money loss or privilege escalation, **S1** = endpoint/task 500 or dead feature, **S2** = correctness/perf/cleanup.

### 2.1 S0 — money and security (Phase P0)

| ID | Location | Symptom | Root cause |
|---|---|---|---|
| D-01 | `commerce/views.py` `PaymentVerifyView` + `commerce/webhooks.py` `_handle_charge_success` | Vendor never receives an earning on the normal buyer flow | Verify marks `Payment.SUCCESS` and orders `PAID`, but never calls `_create_vendor_earning`. Webhook then sees `SUCCESS` and returns early. |
| D-02 | `financials/models.py` `VendorEarning.payout` | Vendor can be paid twice; payout settlement finds zero earnings | `payout` is never assigned anywhere; `VendorEarning.objects.filter(payout=payout)` always matches nothing. |
| D-03 | `admin_panel/views.py` `AdminMarkPayoutPaidView` | One payout marks **every** available earning for that vendor as paid | `filter(vendor=..., status=AVAILABLE).update(...)` ignores `payout`. |
| D-04 | `commerce/views.py` `DisputeActionView` | Any authenticated user can refund any dispute | `permission_classes = [IsAuthenticated]`; no buyer/seller/admin scoping. Refund branch also sets `status=REVERSED` before the `if earning.status == PENDING` check, so the pending-balance branch is unreachable. |
| D-05 | `accounts/serializers.py` `UserRegistrationSerializer` | Public registration can create `admin`/`super_admin` | `role` is in `fields` and has no `validate_role`; `create()` passes it to `create_user`. |
| D-06 | `listings/models.py` `Listing.store`; `listings/serializers.py` | A seller can attach a listing to another seller's store; storeless listings vanish or 500 | `store` is nullable, writable, and never derived server-side. |
| D-07 | `admin_panel/views.py` every view | Invited staff cannot use the matrix; roles with no module grant can still call endpoints | All views use only `IsAdminOrSuperAdmin`, which checks `User.role` and ignores `AdminProfile` and `RolePermission`. |
| D-08 | `hb/settings.py` | Revoking a refresh token does nothing; there is no outstanding-token table | `rest_framework_simplejwt.token_blacklist` is missing from `INSTALLED_APPS` while `BLACKLIST_AFTER_ROTATION = True`. SimpleJWT catches the missing `blacklist()` method, so `POST /auth/refresh/` still returns 200, but rotation never invalidates the old token. |
| D-09 | `accounts/serializers.py` `SellerOnboardingStep3Serializer.save`; `accounts/views.py` `VerificationViewSet.request_verification`; `accounts/serializers.py` `VerificationRequestSerializer` | Admin sees a fake second document pointing at `/media/sole_proprietorship` | `business_type` (e.g. `sole_proprietorship`) is written into `additional_info`, which the admin drawer renders as a document. Onboarding never supplies the required `insurance_certificate`. The legacy verification endpoint writes raw request strings into FileFields, bypassing validation. |
| D-10 | `commerce/webhooks.py` | Lost payments on transient errors; duplicate processing on retries | Handler catches every exception and still returns 200. No event ledger. |
| D-11 | `commerce/views.py` `DisputeActionView` / no refund service | “Refund” never calls Paystack and has no ledger | Status changes and wallet debits happen locally only. |
| D-12 | `commerce/webhooks.py` `_handle_transfer_success/failed/reversed`; `_create_vendor_earning` | Wallet credits and payout debits can land on different wallet rows | Accrual uses `get_or_create(user=..., store=...)` while payout handlers use `get_or_create(user=...)`. A legacy wallet with `store=None` causes an `IntegrityError` on the next accrual or a split balance between the store-less and store-bound wallet. |
| D-13 | `commerce/views.py` `CheckoutView` | Buyers are charged a 5% “escrow” fee; platform revenue is booked nowhere | `ESCROW_RATE` added to `total_amount`; no commission field; the only aggregations that referenced the fee are broken. |
| D-14 | `store/models.py` | Service providers cannot own a store | `Store.user` has `limit_choices_to={'role': SELLER}` and `VerificationViewSet` only serves `SERVICE_PROVIDER`. |
| D-43 | `commerce/views.py` `CheckoutView` → `OrderItem.purchase_type` | Rental orders lose the per-day price; `OrderItem.subtotal` returns `unit_price × quantity` without days | `CartItem.PurchaseType.RENT` is `'rent'`, but `Order.OrderType` choices are `buy/hire/lease`. `'rent'` is copied verbatim, so it never matches `HIRE` or `LEASE` in `OrderItem.subtotal`. |

### 2.2 S1 — 500s and dead features (Phase P1)

| ID | Location | Symptom | Root cause |
|---|---|---|---|
| D-15 | `notifications/tasks.py` | Daily 08:00 task fails | Queries removed `Order.order_type` and `Order.rental_end_date`. |
| D-16 | `analytics/views.py` `AnalyticsViewSet.list` | First request works, every later request 500s for 5 minutes | Caches a dict containing `datetime`; serializer receives a naive object out of cache. |
| D-17 | `admin_panel/views.py` `AdminPaymentListView` | Payments page 500s | `select_related('order', 'order__seller', 'order__listing')`; `Payment` has no `order`. |
| D-18 | `admin_panel/views.py` `AdminPaymentStatsView`, `AdminReportStatsView` | Dashboard cards 500 | `Sum('order__escrow_fee')` traverses a non-existent relation. |
| D-19 | `listings/views.py` `get_queryset` | Storeless listings invisible | `store__is_published=True` is an inner join. |
| D-20 | `listings/views.py` `destroy` | Deleting a listing never checks active orders | `Order.objects.filter(listing=...)` raises `FieldError`, swallowed by `except Exception`. |
| D-21 | `listings/views.py` `publish` | Publish 500s when `listing.store` is null | `log_store_activity(listing.store, ...)` dereferences `None`. |
| D-22 | `commerce/views.py` `OrderExtendRentalView` | Extend rental always 500s | Uses removed `Order.rental_end_date`, `rental_start_date`, `rental_duration_days`, `rental_days_total`. |
| D-23 | `commerce/views.py` `OrderMarkShippedView` | “Ship” jumps to `FULFILLED`, ignores tracking number | Sets `FULFILLED`, accepts no body, never validates carrier/tracking. |
| D-24 | `commerce/serializers.py` `OrderListTrackingSummarySerializer` | Orders list `order_id` is a string; no total | `order_id = CharField(source="order_number")`; `total_amount` absent. |
| D-25 | `commerce/serializers.py` `OrderTrackingDetailSerializer` | Tracking page has no amounts | `monetary_fields` lists four fields that are not in `Meta.fields`. |
| D-26 | `reviews/` | No edit/delete; anyone can review without buying | Only list/create routes; no paid `OrderItem` check. |
| D-27 | `commerce/views.py` `OrderActivityListView` | Seller cannot read the order timeline | Queryset filters `buyer=user` unless staff. |
| D-28 | `commerce/views.py` `OrderDetailView.post` | Buyer cannot cancel a paid order or request a refund | Only `DRAFT` and `PENDING_PAYMENT` allowed; no refund path. |
| D-29 | `store/models.py` `Store.sales_count`; `commerce/views.py` `RecentSalesView` | Sales counts and recent sales drop orders after shipping | Only `PAID` and `FULFILLED` are counted. |
| D-30 | repository root | Two competing schema files; one is empty | `schema.yml` is stale and `schema.yaml` is zero bytes. |
| D-31 | `hb/settings.py` | No test settings, no eager Celery, no CI | `.github/workflows/deploy.yml` deploys directly with no tests, lint, or migration check. Fixed in P0 because every later phase depends on it. |
| D-32 | `listings/serializers.py` | Debug output in production logs | `print("documents_data:", documents_data)`. |

### 2.3 S2 — model, performance, cleanliness (Phase P2/P3)

| ID | Location | Issue |
|---|---|---|
| D-33 | `commerce/views.py` `CheckoutView` | Groups carts by `item.store_id or 'no_store'`, then uses `items[0].listing.user` as seller. Contradicts store-as-vendor and collapses all storeless items into one order. |
| D-34 | `commerce/models.py` `Order.listing` | Single-item assumption is implicit; no `item`/`purchase_type` accessor. |
| D-35 | `core/currency.py` | `convert_currency` returns `float`; checkout and financials re-wrap it in `Decimal(str(...))`. Violates pure Decimal money. |
| D-36 | `financials/tasks.py` | `release_pending_earnings_task` crashes the whole batch on a null `earning.order`; no partial release; no locking. |
| D-37 | `financials/tasks.py` `process_payout_task` | On failure it marks `FAILED` and retries, but never re-credits the wallet; a retry can pay twice if the gateway actually succeeded. |
| D-38 | `apps/health` | Installed app with no models, no URLs, no views, no checks. Pure dead weight. |
| D-39 | Root scripts | `test_paystack.py`, `test_paystack2.py`, `test_posthog.py`, `test_recent_sales.py` are ad-hoc scripts, not tests, and are not collected by pytest. |
| D-40 | `.github/workflows/deploy.yml` | Runs `create_sample_data` on every deploy, which can duplicate mock data. |
| D-41 | `notifications/` | In-app only for most events; email only for a handful; no SMS, push, preferences, or delivery ledger. |
| D-42 | `commerce/views.py` | Most list views lack `select_related`/`prefetch_related`; N+1 on orders, listings, conversations. |

---

## 3. Target domain model

### 3.1 Order grain: one cart item, one Order

```
CheckoutSession 1 ── n Order 1 ── 1 OrderItem
```

- `CheckoutView` iterates `cart_items` and creates **one Order per cart item**.
- Each Order receives `store = item.listing.store`, `seller = store.user`, and one `OrderItem` copied from the cart item.
- `OrderItem.quantity` preserves the quantity. There is no rule that quantity must be 1.
- A single `Payment` covers the whole `CheckoutSession`.
- One Order has one tracking ID, one delivery carrier, one shipment. A vendor never splits one Order.
- A vendor may have multiple Orders from the same buyer; each has its own tracking and lifecycle.

`Order` keeps `id` (integer primary key) and `order_number` (human-readable unique string). `id` is the API key. `order_number` is display-only.

### 3.2 Order model changes

Add:

| Field | Type | Purpose |
|---|---|---|
| `purchase_type` | property from `item.purchase_type` | Convenience; not stored |
| `item` | property returning the single `OrderItem` | Replaces repeated `items.first()` |
| `commission_rate` | `Decimal(5,2)` | Snapshot of `Store.commission_rate` at payment |
| `commission_amount` | `Decimal(14,2)` | Platform revenue for this order |
| `shipped_at` | `DateTimeField(null=True)` | SLA and auto-confirm scheduling |
| `delivered_at` | `DateTimeField(null=True)` | Auto-confirm scheduling |
| `completed_at` | `DateTimeField(null=True)` | Triggers final earnings release |
| `cancelled_at` | `DateTimeField(null=True)` | Audit |
| `cancellation_reason` | `TextField(blank=True)` | Audit |

Keep but reinterpret:

- `subtotal` — goods/rental amount in NGN, **excludes** delivery and commission.
- `delivery_fee` — passes to the vendor in full.
- `total_amount` — exactly `subtotal + delivery_fee`. This is what the buyer pays.
- `escrow_fee` — **legacy only**. New orders always write `0`. Existing paid orders keep their historical value so mock totals do not change. All new reporting uses `commission_amount`.

Change:

- `store` becomes `null=False`.
- `seller` remains, but is always written from `store.user` by the service layer.
- `items` cardinality is enforced at the service layer (one item per order).

### 3.3 Listing and Store ownership

- `Listing.store` becomes `null=False` and `editable=False` in the serializer.
- `Order.store` and `Listing.store` use `on_delete=PROTECT`. Stores are deactivated, never deleted while they own listings or orders.
- The server derives `Listing.store` on create and update:
  - If the request user owns a store, use it.
  - If not, return `400` with `{"error": "Complete seller onboarding before creating a listing."}`.
- `Listing.save()` refuses to persist with `store is None` and raises a domain error caught by the view.
- `Store.user.limit_choices_to` is removed so `SERVICE_PROVIDER` users can own stores.
- `Store.commission_rate` stays the single source of commission configuration. Default `5.00`.

### 3.4 Currency

- All monetary columns on `Order`, `Payment`, `VendorEarning`, `VendorWallet`, `Payout`, `Refund`, `RentalExtension` are **NGN**.
- `OrderItem` gains:
  - `original_currency` (`CharField(3)`)
  - `original_unit_price` (`Decimal(14,2)`)
  - `exchange_rate` (`Decimal(18,8)`) — NGN per unit of original currency at checkout
- Checkout converts once and writes both the original and the NGN value.
- `core/currency.py` gains Decimal-native helpers:
  - `convert_to_ngn(amount, source_currency) -> Decimal`
  - `convert_from_ngn(amount, target_currency) -> Decimal`
  - `money(value) -> Decimal` with `ROUND_HALF_UP` to 2 places
- Existing `convert_currency` remains only for display serializers and is documented as display-only. Checkout, earnings, wallets, payouts, and refunds never call it.
- Rate source remains the existing cached exchange-rate provider. If a rate is missing, checkout fails with `400` rather than silently using `1.0`.

### 3.5 Financial model

```
Order (paid)
  └── VendorEarning (1:1, per Q11)
        ├── commission_amount  → platform revenue
        ├── net_amount         → vendor
        ├── released_amount    → cumulative amount released to available
        └── paid_out_amount    → cumulative amount paid to vendor

Payout 1 ── n PayoutAllocation n ── 1 VendorEarning
```

`VendorEarning` changes:

| Field | Type | Notes |
|---|---|---|
| `order` | `OneToOneField` | stays; 1 earning per order |
| `gross_amount` | Decimal | `order.subtotal + order.delivery_fee` |
| `commission_rate` | Decimal | snapshot |
| `commission_amount` | Decimal | `round(gross_goods * rate/100)` |
| `net_amount` | Decimal | `gross_amount - commission_amount` |
| `release_policy` | choice | `split_50_50` (default), `full` |
| `released_amount` | Decimal default 0 | cumulative |
| `paid_out_amount` | Decimal default 0 | cumulative |
| `first_release_at` | DateTime | `paid_at + 7 days` |
| `final_release_at` | DateTime null | set when the order completes |
| `status` | choices | `pending`, `partially_released`, `available`, `processing`, `paid_out`, `reversed` |
| `is_disputed` | Boolean | freeze |

Removed: `payout` FK. Replaced by `PayoutAllocation`.

`VendorWallet` becomes **one per Store**:

- `store` is a `OneToOneField(Store)`: every store has exactly one wallet.
- `user` is derived and kept for backwards-compatible reads, but writes use `store`.
- `pending_balance` = Σ (`net_amount` − `released_amount`)
- `available_balance` = Σ (`released_amount` − `paid_out_amount`) − amounts reserved by open payouts
- `total_withdrawn` = Σ `paid_out_amount`
- Balances are updated with `F()` expressions inside `select_for_update()` transactions.

`Payout` changes:

- `amount` must equal the sum of its `PayoutAllocation` rows.
- Allocations are selected FIFO from released, undisputed earnings of the store.
- A payout cannot exceed `available_balance`.
- `reference` is unique and used as the Paystack transfer reference.

### 3.6 Commission and fees — worked example

Item price: ₦100,000. Quantity: 2. Delivery: ₦5,000. Store commission: 5%.

| Line | Amount |
|---|---|
| Goods subtotal | ₦200,000.00 |
| Delivery fee | ₦5,000.00 |
| **Buyer pays** | **₦205,000.00** |
| Platform commission (5% of goods only) | ₦10,000.00 |
| **Vendor gross** | **₦205,000.00** |
| **Vendor net** | **₦195,000.00** |

Release schedule with `split_50_50`:

| Event | available_balance increase | Earning status |
|---|---|---|
| Payment success | ₦0 | `pending` |
| Day 7, no dispute | ₦97,500.00 | `partially_released` |
| Order completed, no dispute | ₦97,500.00 | `available` |

If the buyer opens a dispute before a tranche is due, `is_disputed=True` freezes both tranches until resolution. If the dispute is resolved in the vendor's favour, the schedule resumes. If refunded, the earning becomes `reversed`.

### 3.7 Why 50/50 is feasible (Q14)

Yes. It does not require two earning rows, so it preserves Q11. It only requires:

1. A cumulative `released_amount` instead of a boolean “released”.
2. Two timestamps (`first_release_at`, `final_release_at`).
3. A release task that can release 50% then the remainder.
4. Payout allocations so a vendor can withdraw the first tranche while the second is still held.

The main operational caveat is refunds after a tranche has been released. The design allows `available_balance` to go negative in that case, so the debt is visible and is offset by future earnings. Payout requests are rejected while the balance is negative. An admin can also record a manual recovery. This is safer than pretending a released payment can be silently reversed.

---

## 4. Money flows

### 4.1 Checkout

```
POST /checkout/
  validate cart items belong to buyer
  first pass: for each cart item compute subtotal_ngn, delivery_fee, total
      store = item.listing.store            # must exist
      unit_price_ngn = convert_to_ngn(item.unit_price, item.listing.currency)
      subtotal = item.subtotal_ngn
      delivery_fee = 0 for now              # no shipping engine is wired into checkout yet
      total = subtotal + delivery_fee        # no escrow fee
  create CheckoutSession(total_amount=sum(totals), currency=NGN)
  second pass: one Order per cart item
      seller = store.user
      commission_rate = store.commission_rate
      create Order(status=PENDING_PAYMENT, checkout_session, store, seller, ...)
      create one OrderItem(
          purchase_type = map(item.purchase_type)  # cart rent → order hire; lease → lease; buy → buy
          quantity, original_currency, original_unit_price, exchange_rate, NGN prices
      )
  create Payment(checkout_session, amount=grand_total, reference)
COMMIT
initialise Paystack once for the session
  success → store authorization_url/access code, delete checked-out cart items, return orders + payment
  failure → mark Payment FAILED, leave orders PENDING_PAYMENT and leave cart items intact,
            return 502 so the buyer can retry with POST /checkout/session/{id}/retry/
```

- If any cart item lacks a store, checkout returns `400` naming the listing. It never creates a `no_store` bucket.
- All database rows are created in one `transaction.atomic()`.
- Paystack is called **after** the database commit. The external call is not rolled back; a failure is recorded on the payment instead. This avoids an orphaned gateway transaction and prevents the buyer losing their cart.
- `delivery_fee` is deliberately `0` because no shipping-rate selection exists in checkout today. The field stays in the model and the total so a future shipping engine can populate it without another schema change.
- Response keys are unchanged: `orders[].order_id` is the integer Order id, plus `order_number` and `total_amount`.

### 4.2 Payment confirmation

Single service: `apps/commerce/services/payments.py::finalize_payment(payment_id, gateway_payload)`.

```
BEGIN
  payment = Payment.objects.select_for_update().get(pk=payment_id)
  if payment.status == SUCCESS: return already_finalized
  verify amount and currency against gateway payload
  payment.status = SUCCESS; paid_at = now; gateway_response = payload
  for order in payment.checkout_session.orders.select_for_update():
      if order.status == PENDING_PAYMENT:
          order.status = PAID
          order.commission_rate = order.store.commission_rate
          order.commission_amount = money(order.subtotal * rate / 100)
          order.save(...)
          create OrderActivity(PAYMENT_CONFIRMED)
          financials.services.accrue_earning(order)
      enqueue notification(order_paid)
  if payment.rental_extension_id:
      apply_rental_extension(payment.rental_extension)
COMMIT
```

- `accrue_earning` is idempotent by `order` OneToOne and `get_or_create`.
- Wallet increments use `F()`.
- Notifications are dispatched with `transaction.on_commit`.

### 4.3 `GET /payment/verify/{reference}/` — read-only

| Local status | Gateway says | Response |
|---|---|---|
| `success` | anything | `200 {"status":"success"}` |
| `failed` | anything | `200 {"status":"failed"}` |
| `pending` | `success` | `200 {"status":"pending_confirmation","message":"Awaiting webhook confirmation."}` — **no writes** |
| `pending` | `failed`/`abandoned` | `200 {"status":"pending","message":"Payment not completed."}` — **no writes** |
| `pending` | unreachable | `503 {"status":"unknown"}` |

A read-only endpoint has no transaction and never calls `order.save()`. The frontend polls it; the webhook (or the reconciler) does the mutation.

### 4.4 Webhook

- Verify `x-paystack-signature` with `hmac.compare_digest`. Reject invalid signatures with `401`.
- Write a `WebhookEvent` row keyed by `(provider, event_type, gateway_event_id)` with a unique constraint. Duplicate delivery returns `200` without reprocessing.
- Supported events: `charge.success`, `charge.failed`, `refund.processed`, `refund.failed`, `transfer.success`, `transfer.failed`, `transfer.reversed`.
- On a **transient** failure (database, network), return `500` so Paystack retries. On a **permanent** failure (unknown reference, malformed payload), log, mark the event `ignored`, and return `200`.
- Handlers never swallow exceptions silently.

A Celery beat task `reconcile_pending_payments_task` runs every 5 minutes, finds `PENDING` payments older than 10 minutes, calls Paystack verify, and calls `finalize_payment` when the gateway says success. This is the safety net for lost webhooks. It uses the same idempotent service, so it cannot double-credit.

### 4.5 Earnings release

`release_due_earnings_task` runs hourly:

```
for earning in VendorEarning.objects.select_for_update(skip_locked=True)
        .filter(is_disputed=False):
    if status == PENDING and first_release_at <= now:
        amount = half(net) if split_50_50 else net
        release(earning, amount)
    elif status == PARTIALLY_RELEASED and final_release_at <= now:
        release(earning, net - released_amount)
```

`release()`:

1. Guard `earning.released_amount + amount <= earning.net_amount`.
2. `released_amount += amount`.
3. Wallet: `pending_balance -= amount`, `available_balance += amount`, using `F()`.
4. `WalletTransaction(type=EARNING, amount=amount, reference_id=earning.id)`.
5. Status: `PARTIALLY_RELEASED` or `AVAILABLE`.

The task skips `earning.order is None` with a warning instead of aborting the batch.

### 4.6 Payouts

1. Vendor requests amount ≤ `available_balance` for their store.
2. Create `Payout(REQUESTED)` and allocate FIFO from released earnings. Reserve the amount immediately by decrementing `available_balance`, so concurrent requests cannot over-withdraw.
3. `process_payout_task` creates the Paystack recipient and transfer with `payout.reference`.
4. On `transfer.success`: mark allocations settled, increment `paid_out_amount` per earning, set earning `PAID_OUT` when fully paid, and increment wallet `total_withdrawn`. The amount was already reserved in step 2, so `available_balance` is not decremented again.
5. On `transfer.failed`/`reversed`: reverse allocations and re-credit `available_balance` by the reserved amount; set `Payout.FAILED`.
6. Retries are safe because the payout status is checked under `select_for_update()` and the transfer reference is idempotent at Paystack.

Admin “mark payout paid” operates on **that payout’s allocations only**, never on every earning the vendor owns.

### 4.7 Refunds and disputes

- A refund calls `apps/commerce/services/refunds.py::refund_payment(payment, amount, reason, actor)`, which calls Paystack’s refund API and creates a `Refund` row.
- The `refund.processed` webhook finalises:
  - `Payment.REFUNDED` (or `PARTIALLY_REFUNDED` when `amount < payment.amount`)
  - Orders move to `CANCELLED`
  - Earning moves to `REVERSED`
  - Pending balance reduces by the unreleased part
  - Available balance reduces by the released part; negative balances are allowed and block payouts until recovered
- Disputes are opened by the buyer or seller and frozen (`is_disputed=True`). Only an admin can resolve or refund.
- `DisputeActionView` requires `IsAdminOrSuperModule('supports', manage=True)` or superuser.

---

## 5. Order lifecycle and endpoints

### 5.1 Status machine

```
DRAFT → PENDING_PAYMENT → PAID → ORDER_CONFIRMED → ITEM_DISPATCHED → IN_TRANSIT → DELIVERED → FULFILLED
                                                                                         ↘ ACTIVE_HIRE → HIRE_ENDED → ITEM_RETURNED → FULFILLED
PENDING_PAYMENT → CANCELLED
PAID → CANCELLED (buyer before seller confirmation; refund)
any non-terminal → CANCELLED (admin, with refund)
```

Rules:

- `PAID`, `ORDER_CONFIRMED`, `ITEM_DISPATCHED`, `IN_TRANSIT`, `DELIVERED`, `ACTIVE_HIRE`, `HIRE_ENDED`, `ITEM_RETURNED`, `FULFILLED` all count as a completed sale for `Store.sales_count` and recent-sales widgets.
- Only `FULFILLED` and `CANCELLED` are terminal.
- Every transition writes an `OrderActivity` row.
- Every transition is validated in one place: `apps/commerce/services/orders.py::transition(order, event, actor, **payload)`.

### 5.2 Endpoint matrix

| Endpoint | Method | Who | Behaviour |
|---|---|---|---|
| `/orders/` | GET | buyer/seller/admin | List with `select_related` |
| `/orders/` | POST | buyer | Create draft order (kept for compatibility; checkout is the normal path) |
| `/orders/{id}/` | GET | buyer/seller/admin | Detail with totals |
| `/orders/{id}/cancel/` | POST | buyer/seller/admin | Refund if paid; `cancellation_reason` |
| `/orders/{id}/ship/` | POST | seller of `order.store` | Requires `tracking_id` + `delivery_carrier`; `PAID`/`ORDER_CONFIRMED` → `ITEM_DISPATCHED` |
| `/orders/{id}/confirm-receipt/` | POST | buyer | `DELIVERED` → `FULFILLED`; sets `completed_at`; releases final tranche |
| `/orders/{id}/items/{item_id}/extend-rental/` | POST | buyer | Creates a paid `RentalExtension`; applies dates only after payment |
| `/orders/{id}/extend-rental/` | POST | buyer | Returns `400` with `item_id` and the correct endpoint when the order has one item |
| `/orders/{id}/activity/` | GET | buyer/seller/admin | Timeline |
| `/orders/{id_or_number}/tracking/` | GET/PATCH | buyer/seller/admin | Tracking detail; PATCH seller-only |
| `/orders/{id_or_number}/tracking/update/` | POST | seller | State machine event |
| `/orders/{id}/dispute/` | POST | buyer/seller | Open dispute; freezes earning |
| `/disputes/{id}/action/` | POST | admin | Resolve or refund through the refund service |

### 5.3 Rental extension

New model `RentalExtension`:

| Field | Type |
|---|---|
| `order_item` | FK |
| `additional_days` | PositiveInteger |
| `previous_end_date` | Date |
| `new_end_date` | Date |
| `amount` | Decimal (NGN) |
| `payment` | OneToOne Payment |
| `status` | `pending_payment`, `paid`, `cancelled` |
| `created_at` | DateTime |

Flow:

1. Buyer posts `duration_days` or `new_end_date`.
2. Validate: buyer owns the order, item is `hire`/`lease`, order is `PAID`/`ORDER_CONFIRMED`/`ACTIVE_HIRE`, new date is in the future and after the current end date.
3. Amount = `unit_price × quantity × additional_days`.
4. Create `Payment` with `rental_extension` set, initialise Paystack, return `authorization_url`.
5. On payment success, `apply_rental_extension` updates `OrderItem.rental_end_date` and `duration_days`, increments `Order.subtotal`, `Order.total_amount`, and the single `VendorEarning` (`gross_amount`, `commission_amount`, `net_amount`, tranche timestamps), then writes activity and notifies both parties.
6. The extension amount is **additional** to the original order and follows the same 50/50 release policy.

### 5.4 Shipment

- No `Shipment` model.
- `Order.tracking_id` and `Order.delivery_carrier` are the single source of truth.
- `POST /orders/{id}/ship/` requires both fields.
- `PATCH /orders/{id}/tracking/` updates them later.
- The buyer's tracking page reads `tracking_id`, `delivery_carrier`, and the activity timeline from the same order.

---

## 6. Reviews

- Keep list/create; add retrieve/update/delete owned by the reviewer.
- A review requires a **paid** `OrderItem` for that listing/store by the reviewer, with order status in the paid set.
- A reviewer can edit or delete their own review; admins can delete any review.
- Store reviews require a paid order from that store.
- Ratings recompute store/listing aggregates after every write.
- One review per reviewer per listing/store (already enforced by validation; add a DB unique constraint).

---

## 7. Notifications — every channel

### 7.1 Architecture

```
domain event
  └── notifications.services.dispatch(event_key, recipient(s), context)
        ├── render template
        ├── for each enabled channel:
        │     ├── in_app        → Notification row (synchronous)
        │     ├── email         → Celery task → EmailService/SMTP
        │     ├── sms           → Celery task → Termii/Twilio adapter
        │     ├── push          → Celery task → Web Push (VAPID) / FCM adapter
        │     └── staff_webhook → Slack/Discord for ops events
        └── NotificationDelivery ledger row per attempt
```

- `NotificationPreference(user, category, in_app, email, sms, push)`.
- Transactional categories (security, payments, orders, disputes, verification) always send in-app and email; the user can opt out of SMS/push.
- Marketing categories are opt-in only.
- `NotificationDelivery` records channel, status (`queued`, `sent`, `failed`), provider id, error, attempt count.
- Adapters are no-ops when their env vars are absent, so local development and CI never fail because of missing SMS/push credentials.
- Failures in one channel never block another channel or the business transaction.

### 7.2 Event → channel matrix

| Event | Recipients | In-app | Email | SMS | Push | Staff webhook |
|---|---|---|---|---|---|---|
| Order placed | seller | ✓ | ✓ | ✓ | ✓ | |
| Order paid | buyer, seller | ✓ | ✓ | ✓ | ✓ | |
| Order confirmed | buyer | ✓ | ✓ | | ✓ | |
| Order shipped | buyer | ✓ | ✓ | ✓ | ✓ | |
| Order delivered | buyer, seller | ✓ | ✓ | | ✓ | |
| Order completed | buyer, seller | ✓ | ✓ | | ✓ | |
| Order cancelled | both | ✓ | ✓ | ✓ | ✓ | |
| Refund processed | buyer, seller | ✓ | ✓ | ✓ | ✓ | ✓ |
| Rental due in 3 days | buyer | ✓ | ✓ | ✓ | ✓ | |
| Rental due in 1 day | buyer | ✓ | ✓ | ✓ | ✓ | |
| Rental overdue | buyer, seller | ✓ | ✓ | ✓ | ✓ | |
| Rental extended | seller | ✓ | ✓ | | ✓ | |
| Quote received | seller | ✓ | ✓ | ✓ | ✓ | |
| Quote responded | buyer | ✓ | ✓ | ✓ | ✓ | |
| Quote expiring | buyer | ✓ | ✓ | | ✓ | |
| Inquiry received | seller | ✓ | ✓ | | ✓ | |
| Inquiry replied | buyer | ✓ | ✓ | | ✓ | |
| New message | recipient | ✓ | ✓* | | ✓ | |
| Review received | seller | ✓ | ✓ | | ✓ | |
| Payout requested | vendor, finance | ✓ | ✓ | | ✓ | ✓ |
| Payout processed | vendor | ✓ | ✓ | ✓ | ✓ | |
| Payout failed | vendor | ✓ | ✓ | ✓ | ✓ | ✓ |
| Verification submitted | admins | ✓ | ✓ | | ✓ | ✓ |
| Verification approved | vendor | ✓ | ✓ | ✓ | ✓ | |
| Verification rejected | vendor | ✓ | ✓ | ✓ | ✓ | |
| Dispute opened | both, admins | ✓ | ✓ | ✓ | ✓ | ✓ |
| Dispute resolved | both | ✓ | ✓ | ✓ | ✓ | |
| Listing approved/rejected | seller | ✓ | ✓ | | ✓ | |
| Listing expiring | seller | ✓ | ✓ | | ✓ | |
| Password changed | user | ✓ | ✓ | | | |
| New login / 2FA change | user | ✓ | ✓ | ✓ | | |
| Account suspended | user | ✓ | ✓ | ✓ | | |

\* Email for messages is opt-in per user preference to avoid inbox flooding.

### 7.3 Channels chosen

- **In-app:** database + existing list endpoints. Add `unread_count` if absent.
- **Email:** existing SMTP settings and `EmailService`. Add templates for each event with a plain-text fallback.
- **SMS:** Termii for Nigerian numbers (primary), Twilio as a fallback adapter. Selected by `SMS_PROVIDER`; disabled when unset.
- **Push:** Web Push with VAPID keys for the web app, plus an FCM adapter for a future mobile client. `PushSubscription` model stores endpoint/keys per user/device.
- **Staff webhook:** `OPS_WEBHOOK_URL` for Slack/Discord. Used for money and trust events only.

No channel is mandatory for the app to boot.

---

## 8. Verification documents (the reported bug)

### 8.1 Root cause

`SellerOnboardingStep3Serializer.save()` writes the selected `business_type` into `additional_info`:

```python
additional_info=self.validated_data['business_type']
```

`additional_info` is a free-text field. The admin vendor drawer renders it as a document path, so it prefixes `/media/` and produces:

```
https://api.harbourhubglobal.com/media/sole_proprietorship
```

That is not a file. The first document works because it is a real `business_license` FileField whose `.url` is S3-aware.

Three secondary problems:

1. `insurance_certificate` is required on the model but the onboarding step never collects it, so it is blank.
2. `VerificationViewSet.request_verification` writes `request.data.get(...)` strings directly into FileFields, bypassing DRF file validation.
3. `VerificationRequestSerializer._get_absolute_url` calls `request.build_absolute_uri(file_field.url)`. This is correct for S3 (absolute URLs are returned unchanged) but fragile; it should be centralised and must never receive a non-file value.

### 8.2 Fix

Model:

```python
class VerificationRequest(models.Model):
    class BusinessType(models.TextChoices):
        SOLE_PROPRIETORSHIP = 'sole_proprietorship', 'Sole Proprietorship'
        PARTNERSHIP = 'partnership', 'Partnership'
        LIMITED_LIABILITY = 'limited_liability', 'Limited Liability Company'
        CORPORATION = 'corporation', 'Corporation'
        NGO = 'ngo', 'NGO / Non-profit'

    business_type = models.CharField(max_length=32, choices=BusinessType.choices, blank=True)
    business_license = models.FileField(upload_to='verification/licenses/')
    insurance_certificate = models.FileField(
        upload_to='verification/insurance/', null=True, blank=True)
    government_id = models.FileField(
        upload_to='verification/government_ids/', null=True, blank=True)
    additional_info = models.TextField(blank=True)
```

Shared helper `apps/core/files.py`:

```python
def file_url(file_field, request=None):
    if not file_field or not file_field.name:
        return None
    url = file_field.url              # storage-aware: S3 or local
    if url.startswith(('http://', 'https://')):
        return url
    return request.build_absolute_uri(url) if request else url
```

Serializer output:

```json
{
  "id": 14,
  "business_type": "sole_proprietorship",
  "documents": [
    {
      "key": "business_license",
      "label": "Proof of registration",
      "filename": "13678.jpg",
      "url": "https://harbour-hub-storage.s3.eu-north-1.amazonaws.com/media/verification/licenses/13678.jpg"
    }
  ]
}
```

Rules:

- `documents` contains only fields with a real file.
- `url` always comes from `file_url()`. The backend never concatenates `MEDIA_URL`.
- The admin drawer switches to `documents[]` and stops guessing paths. This is a frontend change, but the backend contract is now explicit.
- The raw file fields remain for backwards compatibility but are read-only.

Onboarding:

- Step 3 validates with DRF FileFields, requires `proof_of_registration`, accepts optional `government_id` and `insurance_certificate`, and stores `business_type` in its own column.
- Re-submission without a new file preserves the existing file.
- Step 3 does **not** change the user's role. Role promotion happens in the explicit “become a seller” flow.
- `VerificationViewSet.request_verification` is either removed in favour of the onboarding endpoints or rewritten to use a validated serializer. The chosen path is rewrite, so existing clients keep a working endpoint.

Data migration:

1. For every `VerificationRequest`, if `additional_info` equals a `BusinessType` value, move it to `business_type` and clear `additional_info`.
2. If `insurance_certificate.name` equals a business-type value (corrupt upload), clear it.
3. Leave real files untouched.
4. No row is deleted.

Tests:

- Local storage: URL starts with `settings.MEDIA_URL`.
- S3 storage override: URL is the bucket host and is not double-prefixed.
- A request with only a business licence returns exactly one document.
- `additional_info` never appears in `documents`.

---

## 9. Admin permissions

### 9.1 Identity

`IsAdminOrSuperAdmin` becomes `IsDashboardStaff`, which accepts:

- `is_superuser`
- `role == SUPER_ADMIN`
- an active `AdminProfile`

This makes invited staff usable and keeps ordinary buyers out.

### 9.2 Module matrix

Every admin view declares:

```python
admin_module = AdminModule.PAYMENTS_FINANCE
admin_require_manage = True   # for writes
```

| View | Module | Manage on writes |
|---|---|---|
| `ReportedContentViewSet` | `SUPPORTS` | yes |
| `VerificationAdminViewSet` | `VENDORS_ONBOARDING` | yes |
| `AdminVendorListView` / `AdminVendorActionView` | `VENDORS_ONBOARDING` | list no, actions yes |
| `AdminListingListView` / `AdminListingActionView` | `LISTINGS_MANAGEMENT` | list no, actions yes |
| `AdminPaymentListView` / `AdminPaymentStatsView` | `PAYMENTS_FINANCE` | no |
| `AdminMarkPayoutPaidView` | `PAYMENTS_FINANCE` | yes |
| `AdminReportStatsView`, `AdminAnalyticsExportView` | `ANALYTICS` | no |
| `AdminOrderViewSet`, `AdminOrderTrackingView` | `ORDERS_BOOKINGS` | no |
| `AdminConversation*` | `MESSAGES_MONITORING` | no |
| `AdminJobListing*` | `CAREERS` | writes yes |
| `AdminUserListView` / `AdminUserActionView` | `USERS_MANAGEMENT` | list no, actions yes |
| `AdminActivityViewSet` | `OVERVIEW_DASHBOARD` | no |
| `AdminGlobalSearchView` | any | filters results by modules the user can view |
| Role matrix endpoints | superuser | yes |

`has_admin_module_permission` short-circuits `StaffRole.SUPER_ADMIN` to `True`, matching the intent of the matrix.

### 9.3 Object scoping

- Admin actions use `get_object_or_404` and log the actor.
- Payout actions load the payout and update only its allocations.
- Refund actions require manage permission and record `Refund`.
- No admin endpoint uses an unscoped `.update()` on a queryset derived from user input.

---

## 10. Health app (Q18)

`apps/health` is empty: no models, no URLs, no views, only boilerplate `tests.py`. Nothing references a health URL; the deploy workflow uses SSH and systemd, not a platform health check.

**Decision:** delete `apps/health` and remove it from `INSTALLED_APPS`. If an uptime monitor or load balancer is added later, introduce a real `/health/` endpoint that checks database, Redis, and Celery ping, returns no secrets, and is unauthenticated. Do not keep an empty app as a placeholder.

---

## 11. Authentication and accounts

- Registration always creates `BUYER`. `role` is removed from `UserRegistrationSerializer.fields`. Any client that sends it gets a validation error naming the field.
- `POST /auth/become-seller/` is the explicit promotion path: sets `role=SELLER`, creates an unpublished `Store`, and starts onboarding. It is idempotent.
- `SERVICE_PROVIDER` keeps its role and can own a store and sell services. Removing the role would break existing rows and invitations; keeping it costs nothing.
- `POST /auth/refresh/` works once `token_blacklist` is installed; logout revokes refresh tokens.
- Password reset and 2FA events dispatch through the notification service.
- Session records are created on login and closed on logout.

---

## 12. Listings, store, and search

- `Listing.store` is derived, never accepted from the client.
- `ListingViewSet.get_queryset` no longer inner-joins on store. Listings are visible when their own status is published and either (a) the store is active/published or (b) the listing is served to its owner/admin.
- New listings without a store return `400`, not a 500.
- `publish` validates `listing.store` exists and the store is active; missing store returns `400`.
- `destroy` checks `OrderItem.objects.filter(listing=instance, order__status__in=PAID_SET)` and pending quotes, and never swallows `FieldError`.
- `StoreListSerializer` exposes `commission_rate` only to the owner/admin, not publicly.
- Search and filters use `select_related('store', 'category')` and `prefetch_related('images')`.

---

## 13. Admin finance reporting

After the model change:

| Card | Source |
|---|---|
| Total volume | `Payment.objects.filter(status=SUCCESS).aggregate(Sum('amount'))` |
| Platform revenue | `VendorEarning.objects.filter(order__status__in=PAID_SET).aggregate(Sum('commission_amount'))` |
| Vendor payouts | `Payout.objects.filter(status=PAID).aggregate(Sum('amount'))` |
| Pending payouts | `Payout.objects.filter(status__in=[REQUESTED, PROCESSING]).aggregate(Sum('amount'))` |
| Total revenue (reports) | same as platform revenue |

Date filters use `paid_at`/`processed_at`, not `created_at`. Currency is NGN. `escrow_fee` is never used for new revenue.

---

## 14. Phased delivery

### Phase P0 — safety net, money, security

Deliverables:

1. `hb/settings_test.py`, `pytest.ini`, factories, and a CI workflow that runs lint, `makemigrations --check`, migrations, and tests.
2. Registration role lock-down (D-05).
3. Dispute authorisation and a real refund service (D-04, D-11).
4. `finalize_payment` service; `PaymentVerifyView` read-only; webhook idempotency ledger (D-01, D-10).
5. Earning accrual on every successful payment (D-01).
6. Payout allocation model and safe payout settlement (D-02, D-03, D-12, D-37).
7. `token_blacklist` installation (D-08).
8. `Listing.store` derivation and non-null migration (D-06).
9. Verification document repair, `business_type` field, onboarding validation (D-09, D-14).
10. Admin module permissions (D-07).
11. Delete `apps/health` (D-38).
12. Map cart `rent` to order `hire` at checkout so current rental totals are correct (D-43). This is a one-line correctness fix that precedes the full P2 redesign.

Exit criteria:

- Paying an order always creates exactly one earning.
- A second webhook delivery or a verify poll cannot create a second earning.
- A payout cannot mark unrelated earnings paid.
- A non-admin receives `403` on every admin endpoint; a `read_only` staff member cannot manage.
- Registering with `role=super_admin` returns `400` and the user is not created.
- Creating a listing with `store=<other store>` ignores the value.
- The reported vendor’s second document is absent from `documents[]` and `business_type` reads `sole_proprietorship`.
- CI is green.

### Phase P1 — every 500 and dead feature

Deliverables:

1. Rental reminder task (D-15).
2. Analytics cache serialisation (D-16).
3. Admin payment list and stats (D-17, D-18).
4. Listing visibility, delete guard, publish guard (D-19, D-20, D-21).
5. Extend-rental legacy response and ship endpoint (D-22, D-23).
6. Order list/tracking serializer contracts (D-24, D-25).
7. Seller order timeline and paid cancellation/refund (D-27, D-28).
8. Review CRUD and paid-order gate (D-26).
9. Sales counts across the paid lifecycle (D-29).
10. Schema cleanup and CI schema check (D-30).
11. Remove debug print (D-32).

Exit criteria:

- A route smoke test hits every URL and asserts no `500`.
- Celery beat tasks run eagerly in tests without `FieldError`.
- The admin payments page and dashboard cards load.
- Every state transition in the matrix is reachable and unauthorised transitions return `400`.

### Phase P2 — order-model redesign and money flow

Deliverables:

1. One cart item → one Order; store-authoritative checkout; no buyer fees; `rent → hire` purchase-type mapping (D-13, D-33, D-43).
2. Commission snapshots and platform revenue.
3. Currency snapshot fields and Decimal-native conversion (D-35).
4. `VendorEarning` tranche release (50/50), `PayoutAllocation`, per-store wallets (D-36).
5. `RentalExtension` payment flow.
6. `Refund` model and webhook finalisation.
7. Notification dispatcher with every channel (D-41).
8. `Order` convenience accessors and lifecycle service (D-34).

Exit criteria:

- A cart with three items from three stores creates three orders, each with one item.
- A cart with three items from one store still creates three orders.
- Buyer total equals subtotal + delivery, with zero fees.
- Platform revenue equals the sum of commissions, not buyer fees.
- 50% becomes available on day 7 and the remainder on completion.
- A vendor can withdraw the first tranche while the second is held.
- Rental extension changes dates only after payment.
- A refund marks the earning reversed and does not leave a phantom balance.

### Phase P3 — performance and cleanup

Deliverables:

1. `select_related`/`prefetch_related` on order, listing, conversation, and admin lists (D-42).
2. Indexes for the new query patterns (`Order(buyer, -created_at)`, `Order(store, -created_at)`, `VendorEarning(store, status)`, `Payment(status, created_at)`).
3. Delete root ad-hoc scripts or move them to `scripts/manual/` (D-39).
4. Make `create_sample_data` idempotent and gate it behind `SEED_SAMPLE_DATA=true` (D-40).
5. Flake8 rules for `F401`, `F821`, `F841`; remove unused imports.
6. Delete any endpoint that remains unimplemented after P0–P2. No stub views.

Exit criteria:

- Key list endpoints execute a bounded number of queries (asserted with `django_assert_num_queries`).
- Lint is clean.
- Deploy no longer reseeds data unless explicitly asked.
- No empty app or empty route remains.

---

## 15. Data reconciliation strategy

No data is deleted. The order is **add → backfill → verify → constrain**.

### 15.1 Stores and listings

1. For every `Listing` with `store IS NULL`:
   - If `listing.user.store` exists, set `listing.store` to it.
   - Else create a `Store` for the user with `name = user.company or user.full_name or user.email`, `slug` = unique slug, `is_active=True`, `is_published` = `True` when the listing is published (so existing mock listings do not disappear), `is_verified = user.is_verified`.
2. Report the count before and after.
3. Then add the `NOT NULL` constraint.

### 15.2 Orders

1. Set `Order.store` from `order.items.first().listing.store` when null.
2. Set `Order.seller` from `order.store.user`.
3. Set `Order.commission_rate` from `order.store.commission_rate`; recompute `commission_amount` for paid orders where it is zero.
4. For orders with no `OrderItem`:
   - If `order.extra` contains a listing id and price, create the item.
   - Otherwise leave the order intact and emit it in the reconciliation report. These are historical records that cannot be reconstructed honestly.
5. For unpaid orders with `escrow_fee > 0`, set `escrow_fee=0` and reduce `total_amount` by the fee.
6. For paid orders, freeze totals. Do not rewrite history.

A management command `python manage.py reconcile_orders --dry-run` prints every proposed change. `--apply` writes them. Migrations only add fields; the command performs judgement-based repairs.

### 15.3 Earnings and wallets

1. Link orphan `VendorEarning` rows to orders where the vendor/store/amount match exactly one paid order and no earning exists.
2. Leave ambiguous rows with `order IS NULL`. They remain `pending`, are excluded from release and payout queries, and appear in the reconciliation report for manual mapping. They are not mislabelled as reversed, because no refund has occurred.
3. Merge duplicate `VendorWallet` rows per store: sum balances, keep the oldest row, delete the extras only after the sums are verified.
4. Create a wallet for every store that has earnings but no wallet.

### 15.4 Verification requests

1. Move business-type values out of `additional_info`.
2. Clear corrupt non-path file names.
3. Keep all real files.

### 15.5 Rollback

Every migration is reversible except the final `NOT NULL` constraints. Before applying those, take a database snapshot. If the constraint fails, the migration stops and no data is lost.

---

## 16. Verification and test net

### 16.1 Test settings

`hb/settings_test.py`:

- imports `hb.settings`
- PostgreSQL test database (matches production; CI provides a service container)
- `CELERY_TASK_ALWAYS_EAGER = True`
- `EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'`
- `USE_S3 = False`, temporary `MEDIA_ROOT`
- fast password hasher
- `RATELIMIT_ENABLE = False`
- Sentry disabled

### 16.2 Factories

`tests/factories.py`: `UserFactory`, `StoreFactory`, `ListingFactory`, `CartItemFactory`, `CheckoutSessionFactory`, `OrderFactory`, `PaymentFactory`, `VendorEarningFactory`, `WalletFactory`, `PayoutFactory`.

### 16.3 Required test suites

| Suite | Asserts |
|---|---|
| `test_money.py` | Decimal throughout, rounding half-up, no buyer fee, commission on goods only, rate snapshot |
| `test_checkout.py` | N items → N orders; one item each; correct store/seller; gateway failure preserves the cart and marks the payment failed; totals |
| `test_payments.py` | finalize is idempotent; verify never mutates; duplicate webhook ignored; bad signature rejected |
| `test_earnings.py` | exactly one earning per order; 50/50 schedule; dispute freeze; refund reversal; null-order skip |
| `test_payouts.py` | allocation prevents double pay; failure re-credits; over-withdrawal rejected |
| `test_auth.py` | registration forces buyer; refresh works; logout revokes; role escalation rejected |
| `test_admin_permissions.py` | every role × module × method |
| `test_listings.py` | store derived; client store ignored; storeless repair; publish/delete guards; visibility |
| `test_orders.py` | state machine; ship requires tracking; confirm receipt; cancel/refund; seller timeline |
| `test_rental_extension.py` | amount, payment gating, date update, earning adjustment |
| `test_reviews.py` | purchase gate; CRUD ownership; aggregate refresh |
| `test_verification_docs.py` | local URL, S3 URL, no fake document, business_type migration |
| `test_notifications.py` | channel dispatch, preference opt-out, failure isolation, delivery ledger |
| `test_tasks.py` | rental reminders, release task, payout retries, reconciler |
| `test_smoke_routes.py` | enumerate URL patterns; authenticated and anonymous; no 500 |

### 16.4 CI

`.github/workflows/ci.yml`:

1. Python 3.11, PostgreSQL service, Redis service.
2. `pip install -r requirements-dev.txt`.
3. `flake8 apps hb`.
4. `python manage.py makemigrations --check --dry-run`.
5. `python manage.py migrate`.
6. `python manage.py spectacular --file /tmp/schema.yml --validate`.
7. `pytest -q`.

The deploy workflow depends on CI and runs migrations only after tests pass. `create_sample_data` is removed from automatic deploys.

### 16.5 Manual acceptance script

A short `scripts/smoke.sh` (or PowerShell equivalent) that:

1. Registers a buyer, a seller, and an admin.
2. Runs seller onboarding and uploads two documents.
3. Creates a store and a listing.
4. Adds two cart items.
5. Checks out and receives two orders.
6. Simulates `charge.success` and confirms two earnings.
7. Runs the release task with a mocked clock.
8. Requests a payout and settles it.
9. Opens and resolves a dispute.
10. Fetches the admin vendor drawer and asserts both document URLs resolve.

---

## 17. API contract changes and frontend coordination

| Endpoint | Before | After |
|---|---|---|
| `GET /orders/my-orders/` | `order_id` = order number string | `order_id` = integer; `order_number` added |
| `GET /orders/{id}/tracking/` | `order_id` = order number; no totals | `order_id` integer; `order_number`; `total_amount`, `subtotal`, `delivery_fee`, `currency` |
| `POST /checkout/` | orders grouped by store | one order per cart item; same response keys |
| `POST /orders/{id}/ship/` | no body; jumps to fulfilled | requires `tracking_id` + `delivery_carrier` |
| `POST /orders/{id}/extend-rental/` | 500 | `400` with `item_id` and the correct endpoint |
| `GET /payment/verify/{ref}/` | mutated state | read-only status |
| `GET /admin/verifications/{id}/` | raw file fields + polluted `additional_info` | `business_type` + `documents[]` |
| Seller store UI | “ESCROW fee” | “Sales Commission” (frontend label; backend field `commission_amount`) |
| Registration | accepted `role` | rejects `role` |

The orders detail page already fetches by integer `order_id`; only the list displays `order_number`. This contract matches the frontend’s current intent.

---

## 18. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Changing `order_id` from string to int breaks a hidden frontend use | Keep `order_number` in every payload; the user confirmed the orders page uses the integer |
| Making `Listing.store` non-null breaks listing creation | Explicit `400` with onboarding guidance; auto-create stores only during data migration |
| 50/50 release creates negative vendor balances after a late refund | Allow negative only for reversal, block withdrawals, surface the balance in the vendor dashboard |
| Webhook outage delays confirmation | Read-only verify poller plus the 5-minute reconciler using the same idempotent service |
| Notification fan-out slows requests | In-app synchronous, all external channels asynchronous with retries |
| Data migration guesses wrong on orphan orders | Separate management command with dry-run; migrations only add fields |
| Admin matrix locks out existing staff | Active `AdminProfile` is now accepted; super admin short-circuits |
| Deleting `apps/health` removes a future hook | Documented replacement endpoint if monitoring is added |

---

## 19. Explicitly out of scope

- Crypto payments. The buyer-side fee model can be revisited when that is added.
- Multi-currency settlement. Display conversion only for now.
- Splitting one order into multiple shipments.
- A mobile app client. The push adapter is designed for it but the client is not built here.
- Rebuilding the admin frontend. Only the API contract and the label change are in scope.
- Rewriting the search engine.

---

## 20. Decision record (from the discovery session)

| # | Decision |
|---|---|
| Q1 | Four gated phases: P0 safety net + money/security, P1 500s/dead features, P2 order redesign, P3 perf/cleanup |
| Q2 | No production data, but mock data is live and important. Reconcile, never reset |
| Q3 | `id` is the integer API key; `order_number` is display-only |
| Q4 | One cart item becomes one Order |
| Q5 | No splitting one order; each order has its own tracking ID; no `Shipment` model |
| Q6 | Item-level extend-rental endpoint; legacy path returns guidance |
| Q7 | The store is the authoritative vendor |
| Q8 | `Listing.store` is non-null and server-derived |
| Q9 | Keep `SERVICE_PROVIDER`; let them own stores |
| Q10 | Buyers pay no fees; platform earns seller commission only |
| Q11 | One `VendorEarning` per order, with tranche tracking |
| Q12 | Webhook is canonical; verify is a read-only poller |
| Q13 | NGN settlement; conversion is display-only; Decimal everywhere |
| Q14 | 50% after 7 days, remainder on completion — feasible with tranche tracking and payout allocations |
| Q15 | Registration always creates a buyer; seller onboarding is separate |
| Q16 | Full review CRUD with a paid-order requirement |
| Q17 | Enforce the full `AdminModule` permission matrix |
| Q18 | Health app is unused; delete it |
| Q19 | Aggressive dead-code deletion with lint enforcement |
| Q20 | Every notification channel: in-app, email, SMS, push, staff webhook |

---

## 21. Definition of done

The work is complete when:

1. All four phase exit criteria are met and CI is green.
2. A buyer can add several items, pay once, and receive one order per item with correct totals and no fees.
3. Every paid order produces exactly one earning, released 50/50, and a vendor can withdraw the released portion without risking a double payout.
4. A missed webhook is recovered by the reconciler without double-crediting.
5. A refund reverses the earning and the wallet correctly.
6. A vendor can ship, a buyer can confirm receipt, and a rental can be extended only after payment.
7. No endpoint in the URL map returns 500 in the smoke test.
8. Admin endpoints enforce the module matrix for every staff role.
9. The vendor verification drawer shows only real, resolvable documents.
10. `create_sample_data` is idempotent and never runs automatically in production.
11. There is no empty app, no dead root script, and no debug `print` left behind.
