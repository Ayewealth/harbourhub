# Harbour Hub sample data

`create_sample_data` builds a linked, deterministic dataset for local development and demos. It is
**not** a fixture loader and it is **not** safe to point at production: it writes business records
and, with `--clean`, deletes them. Read [Safety](#safety) before running it.

The command lives at
`apps/core/management/commands/create_sample_data.py`; its invariants are pinned by
`tests/test_sample_data.py`.

---

## 1. Gating

Seeding is opt-in. The command refuses to run unless one of these is true:

| Condition | Effect |
|---|---|
| `SEED_SAMPLE_DATA=true` in the environment | Normal run. `hb/settings.py` reads the flag with a `False` default. |
| `--force` | Runs even when the flag is off, and is required for `--clean`. |

```bash
# Normal, additive run (SEED_SAMPLE_DATA=true in .env)
python manage.py create_sample_data

# One-off run without changing the environment
python manage.py create_sample_data --force

# Custom counts
python manage.py create_sample_data --users 50 --listings 150 --orders 30

# Destructive reset. Requires BOTH flags.
python manage.py create_sample_data --clean --force
```

| Flag | Default | Meaning |
|---|---|---|
| `--users` | `30` | Number of `user_N` accounts to ensure, in addition to the super admin. |
| `--listings` | `100` | Number of listings to ensure. |
| `--orders` | `20` | Number of `ORD-SAMPLE-*` orders to attempt. |
| `--clean` | off | Delete seeded business data and every non-super-admin user first. Requires `--force`. |
| `--force` | off | Ignore the `SEED_SAMPLE_DATA` gate and allow `--clean`. |

`--clean` deletes notifications, inquiry replies, reviews, wallet transactions, earnings, payouts,
wallets, payments, order activity, orders, cart items, carts, quotes, inquiries, listing images,
saved items, listings, store activity, stores, verification requests, categories, and every user
whose role is not `super_admin`. It does **not** delete super admins, admin-panel profiles, support
tickets, compliance documents, conversations, or other records it never creates.

The whole handler is wrapped in `@transaction.atomic`, so a failure rolls the run back.

---

## 2. Determinism

The command seeds both Faker and Python's `random` with a fixed value:

```python
SAMPLE_SEED = 20261029
```

That makes the *shape* of the data repeatable: the same owners, category cycle, listing titles, and
order numbers. It does not promise byte-identical values across Python or Faker versions, and it does
not make the command overwrite rows that already exist.

Stable natural keys are used instead of random ones wherever a re-run must match:

| Record | Natural key |
|---|---|
| Sample user | `username = user_1 … user_N` |
| Sample user email | `{username}@sample.harbourhub.com` |
| Store | `slug = store-{username}` |
| Listing | `title = {leaf category name} Listing {i+1}` (1-based) |
| Order | `order_number = ORD-SAMPLE-0001 …` (`%04d`) |
| Payment | `reference = PAY-{order_number}` |
| Category | `name` (and `parent` for children) |
| Saved item | `(user, listing)` |
| Review | `(listing, reviewer)` / `(store, reviewer)` |
| Earning | `order` (one-to-one) |

`ORDER_NUMBER_PREFIX = "ORD-SAMPLE-"`.

---

## 3. What is created

With the defaults (`--users 30 --listings 100 --orders 20`) a fresh database gets:

| Entity | Approximate count | Notes |
|---|---|---|
| `User` | 1 super admin + 30 sample users | 15 buyers, 10 sellers, 5 service providers from a seeded shuffled role list. |
| `UserPreference` | one per sample user | `interested_categories` is three random category ids. |
| `DeliveryDetail` | one per sample user | `is_default=True`, country `Nigeria`. |
| `VerificationRequest` | one per seller/provider | Randomly `approved` or `pending`; approved ones are approved by the admin. |
| `Category` | 20 | 5 parents × 3 children. |
| `Store` | 15 | One per seller/provider; `is_active=True`, `is_published=True`, default 5% commission. |
| `Listing` | 100 | Published, NGN, owners and leaf categories cycle by index. |
| `ListingImage` | one per listing | Placeholder row (`sort_order=0`, `is_primary=True`) with no uploaded file. |
| `Inquiry` | 1–3 per listing | From a random buyer who is not the listing owner. |
| `InquiryReply` | ~50% of inquiries | Vendor reply, with an occasional buyer follow-up. |
| `QuoteRequest` | ~half of rental listings | Even-indexed rentals only; `purchase_type=rent`. |
| `SavedItem` | ~20 | Every third buyer is skipped; two picks each. |
| `Order` | up to 20 | `ORD-SAMPLE-0001` onward. A self-purchase is skipped, so the count can be lower. |
| `OrderItem` | one per order | The single priced line. |
| `OrderActivity` | 1–3 per order | `order_placed`, plus `payment_confirmed` and shipped/delivered for fulfilled orders. |
| `CheckoutSession` | one per paid/fulfilled order | The session groups that order and owns its payment. |
| `Payment` | one per paid/fulfilled order | Status `success`, `paid_at` ten minutes after `placed_at`. |
| `Dispute` | ~10% of fulfilled orders | Status `open`, reason `Item not as described`. |
| `BankAccount` | one per selling store | `Sample Bank PLC`, 10-digit number, `is_default` left at its model default. |
| `VendorEarning` | one per paid/fulfilled order | Created through `accrue_earning`. |
| `VendorWallet` | one per store with a paid/fulfilled order | Created on demand by the financial services. |
| `WalletTransaction` | one per accrual, plus one per release | Audit rows written by `accrue_earning` / `release_earning`. |
| `ListingReview` / `StoreReview` | one each per fulfilled order | Ratings 3–5 and 4–5; `get_or_create` prevents duplicates. |
| `Notification` | 3–7 per user | Only for users that have none. |

Order status is chosen from `paid`, `fulfilled`, and `pending_payment`. Only `paid` and `fulfilled`
orders get a checkout session, payment, and earning. Fulfilled orders are shipped and delivered in
the activity log, and their earning is released in full.

### Accounts

The command **does not print credentials**. Use these known values:

| Account | Username | Email | Password |
|---|---|---|---|
| Super admin (created only if none exists) | `admin` | `admin@harbourhub.com` | `password123` |
| Sample users | `user_1 … user_N` | `{username}@sample.harbourhub.com` | `password123` |

If a super admin already exists, the command reuses it and does not reset its password. If a
`user_N` username already exists, that user is reused as-is; its password is not reset either.

### What is deliberately not created

The command does not create `Cart` / `CartItem` rows, `Payout` rows, `Conversation` / `Message`
rows, `SupportTicket`, `ComplianceDocument`, `AdminProfile`, `ShippingProfile`, `JobListing`,
`PlatformConfig`, `ListingView`, `ListingDocument`, OTPs, password-reset tokens, 2FA records, or
`UserSession` rows. A payout must be requested through the API, and a conversation is opened by
messaging or by an inquiry flow that uses the service layer.

---

## 4. Money invariants in the seeded data

Every seeded order is NGN and internally consistent:

```text
Order.subtotal            = unit_price × quantity × (duration_days or 1)
Order.delivery_fee        = random 0–5,000 for buy orders, 0 for rentals
Order.total_amount        = subtotal + delivery_fee
Order.escrow_fee          = 0.00
Order.commission_rate     = store rate for paid/fulfilled orders, 0 for pending
Order.commission_amount   = round(subtotal × rate / 100) for paid/fulfilled, 0 for pending
OrderItem.original_currency   = NGN
OrderItem.original_unit_price = OrderItem.unit_price
OrderItem.exchange_rate       = 1.00000000

VendorEarning.gross_amount      = order.subtotal + order.delivery_fee
VendorEarning.commission_amount = order.commission_amount
VendorEarning.net_amount        = gross_amount − commission_amount

VendorWallet.pending_balance + VendorWallet.available_balance
    = sum of net_amount for that store's earnings
```

The buyer pays no platform fee. Delivery passes to the vendor in full, and commission is charged on
goods only. Fulfilled orders have `released_amount == net_amount`; paid orders start in
`pending_balance` with `first_release_at = now + 7 days`.

These are exactly the assertions in `tests/test_sample_data.py::test_seeded_orders_and_earnings_carry_consistent_money`.

---

## 5. Idempotency

Re-running without `--clean` is additive and should add no duplicates:

- Categories, stores, listings, saved items, reviews, and earnings are looked up by their natural
  keys.
- Orders are looked up by `order_number`; an existing order is reused.
- Notifications are skipped entirely for a user who already has any.
- Inquiries are skipped for a listing that already has any.
- Quote requests are skipped for a rental listing that already has one.

`tests/test_sample_data.py::test_second_run_adds_no_duplicates` snapshots the row counts for every
created entity, runs the command again, and asserts the snapshot is unchanged. The test uses
`--users 12 --listings 24 --orders 12`, not the defaults.

A re-run can still change random values on *new* rows if the prior run left some natural key
missing, and it never repairs a row that was edited by hand. To get a clean, reproducible dataset,
use `--clean --force` on a disposable database.

---

## 6. Verifying a seed

```bash
# The pinned behaviour
python -m pytest tests/test_sample_data.py -q

# Row counts and money consistency
python manage.py shell -c "
from apps.commerce.models import Order
from apps.financials.models import VendorEarning, VendorWallet
from decimal import Decimal
for o in Order.objects.all():
    assert o.total_amount == o.subtotal + o.delivery_fee
    assert o.escrow_fee == Decimal('0.00')
    assert o.seller_id == o.store.user_id
for e in VendorEarning.objects.all():
    assert e.net_amount == e.gross_amount - e.commission_amount
    assert e.commission_amount == e.order.commission_amount
print(Order.objects.count(), 'orders OK')
"
```

Expected sample values you can use in walkthroughs:

| Value | Example |
|---|---|
| Order number | `ORD-SAMPLE-0001` |
| Payment reference | `PAY-ORD-SAMPLE-0001` |
| Store slug | `store-user_2` |
| Listing title | `Drill Bits Listing 1` |
| Admin login | `admin@harbourhub.com` / `password123` |
| Buyer login | `user_1@sample.harbourhub.com` / `password123` |

The exact account that owns a given listing depends on the seeded role shuffle. Query
`Listing.objects.get(title=...)` or `Store.objects.get(slug=...)` rather than assuming a username.

---

## 7. Display currency vs stored money

Sample data is stored in **NGN**. `CurrencyConverterMixin` converts monetary fields for *display*
only, based on the caller's preference (user preference, then the `hh_currency` cookie, then the
`hh-currency` header, then `USD`). Money movement (`convert_to_ngn`, `convert_from_ngn`) is separate
and always stores NGN.

Production rates come from `https://open.er-api.com/v6/latest/USD`, cached for one hour under
`harbour_hub_exchange_rates_usd`. If the provider is unreachable the fallback table is USD `1.0`,
NGN `1492.53`, EUR `0.925`, GBP `0.791`.

The test suite must never touch the network. `tests/conftest.py` installs an autouse fixture that
seeds the cache with fixed USD-base rates:

| Currency | Rate |
|---|---|
| USD | `1.0` |
| NGN | `1500.0` |
| EUR | `0.92` |
| GBP | `0.79` |
| CAD | `1.36` |
| AUD | `1.52` |
| JPY | `149.0` |
| CNY | `7.24` |

Those are the rates to use when writing an example response for a non-NGN display currency. Do not
copy them into production configuration; they exist to keep tests offline.

---

## 8. Safety

- **Never run `--clean` against a database whose data you need.** It deletes every non-super-admin
  user and all seeded business records.
- Without `--clean`, the command is additive. It still creates real rows, so point it at a
  development database, never production.
- The command is atomic, but `--clean` is still a destructive operation inside that transaction.
- The dataset contains fake people, fake bank accounts, and fake reviews. Do not treat it as
  production evidence.

Related reading: [data-model.md](data-model.md) for the entities and invariants,
[api/examples.md](api/examples.md) for request/response walkthroughs, and
[api/messages.md](api/messages.md) for the exact messages the API returns.
