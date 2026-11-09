# Harbour Hub data model

This document describes the domain as the code implements it: the entities, how they relate, the
constraints the database enforces, and the invariants the services protect. It is derived from
`apps/*/models.py` and `apps/*/services/`. When code and this document disagree, the code is
authoritative and the document must be fixed in the same change.

Money is stored in **NGN Decimal**. The buyer pays no platform fee; the platform earns a seller
commission on goods only. See [Money invariants](#money-invariants).

---

## 1. Domain map

```
                              ┌──────────────────────┐
                              │ accounts.User        │
                              │ role: buyer/seller/  │
                              │ service_provider/    │
                              │ admin/super_admin    │
                              └──────────┬───────────┘
                                         │ 1:1
                              ┌──────────▼───────────┐
                              │ store.Store          │  the vendor authority
                              │ commission_rate 5.00 │
                              └──────────┬───────────┘
                                         │ 1:N
                    ┌────────────────────┼─────────────────────┐
                    │                    │                     │
          ┌─────────▼────────┐  ┌────────▼────────┐  ┌─────────▼─────────┐
          │ listings.Listing │  │ financials.     │  │ financials.       │
          │ store NOT NULL   │  │ VendorWallet    │  │ BankAccount       │
          └────┬───────┬─────┘  │ 1 per store     │  └─────────┬─────────┘
               │       │        └────────┬────────┘            │
      ┌────────▼──┐ ┌──▼──────────┐      │                     │
      │ Listing   │ │ QuoteRequest│      │                     │
      │ Image /   │ │ (buyer →    │      │                     │
      │ Document  │ │  vendor)    │      │                     │
      └───────────┘ └──────┬──────┘      │                     │
                           │             │                     │
      User ──1:1──► Cart ──1:N──► CartItem                    │
                                         │                     │
                    CartItem ──checkout──► CheckoutSession ──1:1──► Payment
                                                │ 1:N                │
                                                ▼                    │ 1:N
                                             Order ──1:N──► OrderItem
                                                │ 1:N                │
                                                ├──► OrderActivity   └──► RentalExtension (1:1 payment)
                                                ├──► Dispute
                                                └──1:1──► VendorEarning ──N:M via PayoutAllocation──► Payout
                                                                                              │
                                                                                              ▼
                                                                                        BankAccount
```

The **Store** is the vendor. `Order.seller`, `VendorEarning.vendor`, `Payout.vendor`, and
`VendorWallet.user` are denormalised copies of `Store.user`; writes resolve the store first.

---

## 2. Entities by app

### accounts

| Model | Key fields | Purpose |
|---|---|---|
| `User` | `email` unique, `role`, `is_verified`, `is_active` | Custom user. Email is the login field. Registration always creates `buyer`. |
| `PasswordResetToken` | `token` unique, `expires_at`, `used` | One-shot password reset. |
| `VerificationRequest` | `user`, `status`, documents | Seller/service-provider verification. `approve()` / `reject()` set `reviewed_by` and `reviewed_at`. |
| `OneTimePassword` | `email`, `code`, `purpose`, `expires_at`, `used` | OTP-first registration or login. |
| `DeliveryDetail` | `user`, address fields, `is_default` | Saved shipping address. Cart items and orders reference it. |
| `UserPreference` | `user` (1:1), `preferred_currency`, email flags | Display currency and account email preferences. |
| `UserTwoFactor` | `user` (1:1), `secret`, `is_enabled` | TOTP 2FA. |
| `UserSession` | `user`, `token_jti` unique, `is_active` | Login session ledger; removing a session blacklists its JWT. |

### store and categories

| Model | Key fields | Purpose |
|---|---|---|
| `Store` | `user` (1:1), `slug` unique, `commission_rate`, `is_active`, `is_published` | The vendor. A user has at most one store. |
| `StoreActivity` | `store`, `action`, `message` | Storefront audit trail (listing published, etc.). |
| `ShippingProfile` | `store`, zone, carrier, flat rate | Per-store shipping option. |
| `Category` | `name` unique, `slug` unique, `parent`, MPTT tree fields | Hierarchical catalogue. |

`Store.user` is `OneToOneField(related_name="store")`; `user.store` raises `RelatedObjectDoesNotExist`
when absent. `Listing.store` is mandatory and `PROTECT`ed, so a store cannot be deleted while it owns
listings. New stores default to `is_active=True`, `is_published=False`, `is_verified=False`, and
`commission_rate=5.00`.

### listings

| Model | Key fields | Purpose |
|---|---|---|
| `Listing` | `user`, `store` (NOT NULL), `category`, `listing_type`, `price`, `currency`, `status` | Marketplace item, rental, lease, or service. |
| `ListingImage` | `listing`, `image`, `is_primary`, `sort_order` | Gallery. The first uploaded image becomes primary if none exists. |
| `ListingDocument` | `listing`, `document`, `name` | Spec sheets and compliance attachments. |
| `ListingView` | `listing`, `user` (nullable), `ip_address` | View counter source. |
| `SavedItem` | `user`, `listing` | Wishlist. Unique on `(user, listing)`. |

`Listing.listing_type` is `sell`, `rent`, `lease`, or `service`. `Listing.status` is `draft`,
`published`, `paused`, `archived`, `flagged`, or `suspended`. A listing can only be checked out when
`status=published`; publishing requires an active store.

### commerce

| Model | Key fields | Purpose |
|---|---|---|
| `QuoteRequest` | `listing`, `buyer`, `store`, `purchase_type`, `quantity`, `duration_days`, `adjustments`, `status` | Buyer asks for a price; vendor counters; buyer moves it to the cart. |
| `CheckoutSession` | `buyer`, `total_amount`, `currency` | Groups every order created by one checkout and owns one payment. |
| `Order` | `order_number` unique, `buyer`, `seller`, `store`, `checkout_session`, `subtotal`, `delivery_fee`, `commission_rate`, `commission_amount`, `total_amount`, `escrow_fee` (legacy), `status` | One vendor's order. One cart item produces one order. |
| `OrderItem` | `order`, `listing`, `quote_request`, `purchase_type`, `unit_price`, `original_*`, `exchange_rate`, rental dates, `delivery_detail` | The priced line. |
| `OrderActivity` | `order`, `event_type`, `message` | Append-only timeline shown to buyer, seller, and staff. |
| `Cart` | `buyer` (1:1) | One active cart per buyer. |
| `CartItem` | `cart`, `listing`, `store`, `purchase_type`, `quantity`, `duration_days`, `delivery_detail`, `locked_subtotal` | A line before checkout. Unique on `(cart, listing, purchase_type)`. |
| `Payment` | `checkout_session` (1:1), `buyer`, `amount`, `reference` unique, `status` | One gateway payment per checkout session, or one per rental extension. |
| `RentalExtension` | `order_item`, `additional_days`, `previous_end_date`, `new_end_date`, `amount`, `payment` (1:1), `status` | A payable extension. Dates move only after payment succeeds. |
| `Refund` | `payment`, `amount`, `reason`, `reference` unique, `status` | A gateway refund against one payment. |
| `Dispute` | `order`, `buyer`, `reason`, `status`, `resolution_notes` | Buyer complaint; opening one freezes the order's earning. |
| `WebhookEvent` | `provider`, `event_type`, `gateway_event_id`, `status`, `payload` | Idempotency ledger. Unique on `(provider, event_type, gateway_event_id)`. |

### financials

| Model | Key fields | Purpose |
|---|---|---|
| `VendorEarning` | `order` (1:1), `vendor`, `store`, `gross_amount`, `commission_amount`, `net_amount`, `release_policy`, `released_amount`, `paid_out_amount`, `is_disputed` | Exactly one earning per paid order. |
| `VendorWallet` | `store` (1:1), `user` (1:1), `pending_balance`, `available_balance`, `total_withdrawn` | One wallet per store. |
| `WalletTransaction` | `wallet`, `transaction_type`, `amount`, `reference_id` | Append-only wallet audit log. |
| `BankAccount` | `user`, `store`, account fields, `is_default`, `is_verified` | Payout destination. |
| `Payout` | `vendor`, `store`, `bank_account`, `amount`, `reference` unique, `status` | Vendor withdrawal request. |
| `PayoutAllocation` | `payout`, `earning`, `amount` | FIFO link between a payout and the earnings it consumes. Unique on `(payout, earning)`. |

### notifications

| Model | Key fields | Purpose |
|---|---|---|
| `Notification` | `recipient`, `notification_type`, `title`, `message`, `priority`, `is_read` | The in-app notification itself. |
| `NotificationPreference` | `user`, `category`, `in_app`, `email`, `sms`, `push` | Per-category channel opt-in. Unique on `(user, category)`. |
| `NotificationDelivery` | `notification`, `recipient`, `event_key`, `channel`, `status`, `provider_id`, `error`, `attempts` | One ledger row per external channel attempt. |
| `PushSubscription` | `user`, `endpoint` unique, `p256dh`, `auth`, `user_agent`, `is_active` | A browser Web Push endpoint. A `410 Gone` response deactivates it. |

### messaging, inquiries, reviews

| Model | Key fields | Purpose |
|---|---|---|
| `Conversation` | `buyer`, `vendor`, `listing` (nullable), `store` | One thread per buyer/vendor/listing. Unique on `(buyer, vendor, listing)`. |
| `Message` | `conversation`, `sender`, `message_type`, `body`, `quote_request`, `reply_to`, `is_read` | Chat message or system event. |
| `Inquiry` | `listing`, `from_user`, `to_user`, contact fields, `status` | Listing question. Creating one also opens a conversation. |
| `InquiryReply` | `inquiry`, `user`, `message` | Threaded reply. |
| `InquiryAttachment` | `inquiry`, `file`, `original_name`, `file_size` | Attachment. |
| `ListingReview` | `listing`, `reviewer`, `rating`, `comment` | Unique on `(listing, reviewer)`. |
| `StoreReview` | `store`, `reviewer`, `rating`, `comment` | Unique on `(store, reviewer)`. |

### support, compliance, admin

| Model | Key fields | Purpose |
|---|---|---|
| `SupportTicket` | `raised_by`, `order`, `listing`, `priority`, `status`, `assigned_to` | Buyer/vendor support case. |
| `ComplianceDocument` | `document_type`, `party`, `order`, `listing`, `status`, dates | Contract/licence/insurance record. |
| `AdminProfile` | `user` (1:1), `staff_role`, `invite_status` | Staff dashboard identity. |
| `RolePermission` | `role`, `module`, `can_view`, `can_manage` | Module matrix. Unique on `(role, module)`. |
| `AdminActionLog` | `admin_user`, `action_type`, `description`, `extra_data` | Staff audit trail. |
| `ReportedContent` | `content_type`, `object_id`, `reason`, `status` | Moderation queue. |
| `PlatformConfig` | singleton: `enable_buy`, `enable_rent`, `enable_services`, `vendor_approval_required`, `listing_approval_required`, `default_currency`, `timezone`, `date_format`, plus fee/notification switches | Platform configuration. `GET /platform-config/` exposes the public subset. |
| `JobListing` | title, department, application URL, `is_active` | Public careers page. |
| `UserSearch`, `Feedback` | search query / feedback vote | Search history and help-centre feedback. |

---

## 3. Invariants

These are the rules a migration, serializer, view, or task must not break.

1. **The store is the vendor.** `Listing.store` is non-null and `PROTECT`ed. A client cannot set it:
   `ListingCreateUpdateSerializer` drops `store` and assigns `request.user.store`. Creating a listing
   without a store fails with `{"store": "Complete seller onboarding before creating a listing."}`.
2. **One store per user.** `Store.user` is `OneToOneField`. A second store for the same user violates
   the database constraint.
3. **One cart per buyer.** `Cart.buyer` is `OneToOneField`. A cart item is unique on
   `(cart, listing, purchase_type)`, so adding the same listing again updates the existing line.
4. **One cart item = one order.** `CheckoutView` loops the selected cart items and creates one
   `Order` per item, all linked to one `CheckoutSession`. The session groups orders across vendors;
   each order keeps its own `seller` and `store`.
5. **One payment per checkout session.** `Payment.checkout_session` is `OneToOneField`. A rental
   extension has its own payment and links back with `RentalExtension.payment`.
6. **Payment is confirmed by webhook, not by the client.** `finalize_payment` is the only function
   that may set `Payment.status=success`. It is idempotent, checks the gateway amount against the
   stored amount in kobo, and returns `False` for an already-successful payment.
7. **Commission is on goods only.** `commission = round(subtotal × commission_rate / 100)`.
   `delivery_fee` passes to the vendor in full. `Order.escrow_fee` exists only for legacy
   compatibility and is always `0.00`; it is not a buyer fee. Serializers expose
   `commission_rate` and `commission_amount`, and keep `escrow_fee` (deprecated) so old clients
   do not break.
8. **Rates are snapshotted at payment.** `finalize_payment` copies `Store.commission_rate` onto
   `Order.commission_rate` and computes `Order.commission_amount`. A later rate change never rewrites
   a completed sale.
9. **Foreign prices are converted once.** `CheckoutView` converts each item's subtotal and unit price
   to NGN and stores `OrderItem.original_currency`, `original_unit_price`, and `exchange_rate`
   (NGN per original unit, 8 decimal places). `Order.currency` is always `NGN`.
10. **One earning per order.** `VendorEarning.order` is `OneToOneField`; `accrue_earning` uses
    `get_or_create`. `gross_amount = subtotal + delivery_fee`, `net_amount = gross - commission`.
11. **Two-tranche release.** `first_release_at = payment time + 7 days`. The first tranche is
    `net_amount / 2`; the remainder is released when the order is fulfilled (`_release_final_tranche`)
    or by `release_pending_earnings_task`. `release_earning` is guarded by `released_amount` and
    never releases more than `net_amount`.
12. **One wallet per store.** `VendorWallet.store` is `OneToOneField`; every write resolves the
    wallet by store. `pending_balance + available_balance` equals the unreversed net of the store's
    earnings (before payouts).
13. **Payouts reserve, then settle or re-credit.** Creating a payout deducts
    `available_balance` and FIFO-allocates released earnings through `PayoutAllocation`. A successful
    transfer (`settle_payout`) adds to `total_withdrawn` and `paid_out_amount`. A failed transfer
    (`fail_payout`) deletes the allocations and re-credits the wallet.
14. **Refunds reverse earnings, never the platform fee only.** `finalize_refund` reverses the earning
    proportionally, marks the payment `refunded`/`partially_refunded`, and cancels the order only on a
    full refund. Wallet balances may go negative on purpose when money was already withdrawn.
15. **Disputes freeze funds.** Opening a dispute sets `VendorEarning.is_disputed=True`. While true,
    `release_earning` and payout allocation skip the earning. Admin `resolve` clears the flag; admin
    `refund` keeps it set while the gateway processes the refund.
16. **Rental dates are set at checkout and move only on paid extension.** The initial
    `OrderItem.rental_start_date`/`rental_end_date` are derived from the quote's preferred date (or
    today) and `duration_days` when the order is created. An extension is a separate
    `RentalExtension` in `pending_payment`; `apply_rental_extension` moves the dates and increases
    `Order.subtotal`/`total_amount` only after its payment is finalized.
17. **Webhooks are idempotent.** `WebhookEvent` is unique on
    `(provider, event_type, gateway_event_id)`. A duplicate returns `200` with `detail=duplicate` and
    performs no side effects. A transient handler failure returns `500` so Paystack retries.
18. **Notification delivery is ledgered per channel.** The `Notification` row is the in-app channel.
    Each external channel gets a `NotificationDelivery` row (`queued` → `sent`/`failed`), and an
    opt-out writes `skipped` with `error="Recipient opted out."` instead of dropping the event.
    Transactional in-app and email are always on.
19. **Ids are the API keys.** Integer `id` is used for lookups. `order_number`, `reference`, and slugs
    are display values unless an endpoint explicitly accepts them.
20. **Deletion is protected where money or history depends on it.** `Order.buyer`/`seller`,
    `Order.store`, `Refund.payment`, `RentalExtension.order_item`, and `Payout.store` use `PROTECT`.
    `VendorEarning.order` cascades with the order; `Payment.checkout_session` cascades with the
    session.

---

## 4. Status machines

### Order

`Order.status` starts at `draft` and is normally moved to `pending_payment` by checkout.

```
draft ──cancel──► cancelled
pending_payment ──cancel──► cancelled
pending_payment ──payment webhook──► paid
paid ──order_confirmed──► order_confirmed
paid / order_confirmed ──item_dispatched──► item_dispatched
item_dispatched ──in_transit──► in_transit
in_transit ──delivered──► delivered
delivered ──order_fulfilled──► fulfilled          (buy/physical goods)
delivered ──hire_started──► active_hire           (hire/lease)
active_hire ──hire_ended──► hire_ended
hire_ended ──item_returned──► item_returned
item_returned ──order_fulfilled──► fulfilled      (hire/lease)
```

For an order containing a hire/lease item, `order_fulfilled` is only allowed from `item_returned`;
for a buy-only order, the hire states are removed from the table. All transitions go through
`apps.commerce.services.orders.transition`, which raises `InvalidTransition` with
`Cannot '{event}' an order in status '{status}'.` or `Unknown event '{event}'.`.

`order_cancelled` is only allowed from `draft`/`pending_payment`. A paid order is cancelled through
the refund flow, which sets `cancelled` directly after the gateway confirms a full refund.

### Payment

```
pending ──charge.success──► success
pending ──charge.failed──► failed
success ──full refund──► refunded
success ──partial refund──► partially_refunded
```

`failed` and `refunded` are terminal in the current code. A retry creates a new reference on the same
`Payment` row while it is still pending; it does not create a second payment.

### Refund

```
pending ──refund.processed──► processed
pending ──refund.failed──► failed
```

`finalize_refund` is idempotent on `processed`.

### QuoteRequest

```
pending ──respond──► responded ──convert / move-to-cart──► converted
pending ──cancel / decline──► cancelled
responded ──decline──► cancelled
```

`cancel` is buyer-only and only from `pending`. `decline` is buyer-only from `pending` or
`responded`. `respond` is listing-owner-only from `pending`. `convert` requires `responded`.

### Dispute

```
open ──admin resolve──► resolved
open / under_review ──admin refund──► under_review ──gateway confirms──► refunded
open / under_review ──buyer or admin cancel──► cancelled
```

`refunded` is set by `finalize_refund` when a full refund closes the order. `cancelled` is set by
`POST /commerce/disputes/{id}/cancel/` and by the admin `cancel` action, and by the refund path when
an order is cancelled without a dispute refund. Both terminal statuses release the order's
earning hold. `resolution_notes` and `resolved_at` record the outcome.

### RentalExtension

```
pending_payment ──payment success──► paid
pending_payment ──gateway init failure──► cancelled
```

`apply_rental_extension` is idempotent: it returns immediately unless the extension is
`pending_payment`.

### VendorEarning

```
pending ──first tranche released──► partially_released ──remainder released──► available
available / partially_released ──allocated to a payout──► processing
processing ──payout settled in full──► paid_out
processing ──partial payout settlement──► partially_released
any state ──refund reverses all net──► reversed
```

`processing` is entered when an earning is FIFO-allocated to a requested payout. Settlement marks it
`paid_out` once `paid_out_amount >= net_amount`, otherwise it returns to `partially_released`.
`partially_released` is also used after a partial payout of an `available` earning.

### Payout

```
requested ──process_payout_task accepts transfer──► processing ──transfer.success──► paid
requested / processing ──transfer.failed / exception──► failed
requested / processing ──admin freeze──► frozen ──admin unfreeze──► requested
```

`paid` and `failed` are terminal. `fail_payout` re-credits the wallet and removes allocations.

### WebhookEvent

```
processed | ignored | failed
```

The row is created before the handler runs. A duplicate key short-circuits with `duplicate`; an
unknown event type is marked `ignored`; a handler exception is marked `failed` and returns `500`.

### NotificationDelivery

```
queued ──provider accepts──► sent
queued ──provider rejects / retries exhausted──► failed
queued ──recipient opted out──► skipped
```

In-app delivery has no ledger row: the `Notification` row itself is the in-app record.

---

## 5. Database constraints and indexes

| Constraint | Where |
|---|---|
| `User.email` unique | `accounts.User` |
| `Store.slug` unique, `Store.user` 1:1 | `store.Store` |
| `Listing.slug` unique | `listings.Listing` |
| `SavedItem (user, listing)` unique | `listings.SavedItem` |
| `Cart.buyer` 1:1 | `commerce.Cart` |
| `CartItem (cart, listing, purchase_type)` unique | `commerce.CartItem` |
| `Order.order_number` unique | `commerce.Order` |
| `Payment.reference` unique, `Payment.checkout_session` 1:1 | `commerce.Payment` |
| `RentalExtension.payment` 1:1 | `commerce.RentalExtension` |
| `Refund.reference` unique | `commerce.Refund` |
| `WebhookEvent (provider, event_type, gateway_event_id)` unique | `commerce.WebhookEvent` |
| `VendorEarning.order` 1:1 | `financials.VendorEarning` |
| `VendorWallet.store` 1:1, `VendorWallet.user` 1:1 | `financials.VendorWallet` |
| `Payout.reference` unique | `financials.Payout` |
| `PayoutAllocation (payout, earning)` unique | `financials.PayoutAllocation` |
| `NotificationPreference (user, category)` unique | `notifications.NotificationPreference` |
| `Conversation (buyer, vendor, listing)` unique | `messaging.Conversation` |
| `ListingReview (listing, reviewer)` unique | `reviews.ListingReview` |
| `StoreReview (store, reviewer)` unique | `reviews.StoreReview` |
| `RolePermission (role, module)` unique | `admin_panel.RolePermission` |

P3 added composite indexes for the hot list paths:

- `Order(store, status, -created_at)`, `Order(seller, status, -created_at)`,
  `Order(buyer, -created_at)`, `OrderItem(order, purchase_type)`.
- `VendorEarning(status, first_release_at)`, `VendorEarning(store, status)`.
- `NotificationDelivery(status, channel)`.

---

## 6. Money invariants in one worked example

A buyer purchases two units at ₦100,000 each with ₦5,000 delivery from a store on the default 5%
commission.

| Step | Stored value |
|---|---|
| `OrderItem.unit_price` | `100000.00` |
| `Order.subtotal` | `200000.00` |
| `Order.delivery_fee` | `5000.00` |
| `Order.escrow_fee` | `0.00` |
| `Order.total_amount` | `205000.00` |
| `Order.commission_rate` (snapshot) | `5.00` |
| `Order.commission_amount` | `10000.00` |
| `VendorEarning.gross_amount` | `205000.00` |
| `VendorEarning.commission_amount` | `10000.00` |
| `VendorEarning.net_amount` | `195000.00` |
| First tranche at day 7 | `97500.00` pending → available |
| Final tranche on fulfilment | `97500.00` pending → available |

The buyer never sees a platform or escrow fee line. The old `escrow_fee` column remains on the row
for compatibility but is always zero.

---

## 7. Where the rules live

| Rule | Code |
|---|---|
| Order transitions | `apps/commerce/services/orders.py` |
| Payment finalisation, commission snapshot, earning accrual | `apps/commerce/services/payments.py` |
| Earning accrual, release, reversal, payout allocation | `apps/financials/services.py` |
| Refund request and finalisation | `apps/commerce/services/refunds.py` |
| Rental extension application | `apps/commerce/services/rental.py` |
| Checkout and one-order-per-item | `apps/commerce/views.py` (`CheckoutView`) |
| Webhook idempotency and dispatch | `apps/commerce/webhooks.py` |
| Notification channel fan-out and ledger | `apps/notifications/services.py`, `channels.py`, `tasks.py` |
| Sample data invariants | `apps/core/management/commands/create_sample_data.py`, `tests/test_sample_data.py` |
