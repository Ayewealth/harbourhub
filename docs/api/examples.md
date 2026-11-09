# Harbour Hub API — worked examples

This document walks through the real request and response shapes for the main
Harbour Hub flows. It describes the code as it exists today. Where a flow is
partial, the gap is called out rather than hidden.

- Endpoint index: [endpoints.md](endpoints.md) (generated from `schema.yml`)
- Exact messages and status codes: [messages.md](messages.md)
- Entities and invariants: [../data-model.md](../data-model.md)
- Seeded accounts and values: [../sample-data.md](../sample-data.md)

---

## 0. Conventions used in every example

| Item | Value |
|---|---|
| Base URL (local) | `http://localhost:8000` |
| Auth header | `Authorization: Bearer <access_token>` |
| Request body | `Content-Type: application/json` unless the endpoint says multipart |
| File upload | `multipart/form-data` |
| Money | Decimal **strings** in responses, e.g. `"250000.00"` |
| Currency | Stored NGN; `currency` is `"NGN"` |
| Display currency | The examples assume `preferred_currency: "NGN"` (see below) |
| Timestamps | ISO 8601 UTC, e.g. `"2026-10-31T09:15:00Z"` |
| Pagination | `{count, next, previous, results}` with a default page size of 20 |
| IDs | Integers. `order_id` is the API key; `order_number` is display-only |
| Buyer fees | None. The buyer pays the goods total. |
| Platform revenue | Seller commission, charged on goods only |

All identifiers below come from the sample dataset in
[sample-data.md](../sample-data.md) or are illustrative. A real run generates
different IDs and order numbers.

### Display currency

Money is always **stored** in NGN. Serializers that inherit
`CurrencyConverterMixin` (`Cart`, `CartItem`, `Order`, `OrderItem`,
`OrderTrackingDetail`, `QuoteRequest`, `VendorEarning`, `VendorWallet`,
`WalletTransaction`) convert monetary fields for **display** to the caller's
preferred currency and append `currency` and `currency_symbol`.

The priority is: user preference, then the `hh_currency` cookie, then the
`hh-currency` header, then `USD`. A `UserPreference` row wins over a header, so
an authenticated sample user with the default preference gets **USD** display
amounts even if the request sends `hh-currency: NGN`.

Every example below assumes both the buyer and the seller set NGN first:

```http
PATCH /auth/preferences/
Authorization: Bearer <access>
Content-Type: application/json

{ "preferred_currency": "NGN" }
```

That keeps the display amounts equal to the stored amounts and makes the
arithmetic readable. If you omit it, the money values change (for example
`250000.00` NGN becomes `166.67` USD at the fixed test rate of 1,500) while the
database and every money movement stay NGN.

### The cast

| Actor | Username | Email | Role |
|---|---|---|---|
| Buyer | `user_1` | `user_1@sample.harbourhub.com` | buyer |
| Seller | `user_2` | `user_2@sample.harbourhub.com` | seller |
| Admin | `admin` | `admin@harbourhub.com` | super_admin |

Password for all seeded accounts: `password123`.

The seller owns **Blue Marine Supply** (`store_id` 7, slug `blue-marine-supply`,
`commission_rate` `"5.00"`) and listing **42**, "Commercial Diving Helmet",
`listing_type: "sell"`, `price: "250000.00"`, `currency: "NGN"`.

The buyer has delivery address **11**:

```json
{
  "id": 11,
  "contact_person": "Ada Obi",
  "country": "Nigeria",
  "address": "12 Marina Road",
  "state": "Lagos",
  "city": "Lagos",
  "zip_code": "101001",
  "phone": "08030000000",
  "is_default": true
}
```

---

## 1. Authentication

### 1.1 Register

`POST /auth/register/` — public, throttled to 20/hour per IP.

Registration always creates a **buyer**. Sending a privileged `role` is
rejected; sellers go through onboarding instead.

```http
POST /auth/register/
Content-Type: application/json

{
  "username": "new.buyer",
  "email": "new.buyer@example.com",
  "password": "Harbour!2026",
  "password_confirm": "Harbour!2026",
  "full_name": "New Buyer"
}
```

```http
HTTP/1.1 201 Created

{
  "username": "new.buyer",
  "email": "new.buyer@example.com",
  "full_name": "New Buyer",
  "company": null,
  "phone": null,
  "location": null
}
```

`password`, `password_confirm`, and `role` are write-only and never echoed.

Rejected role:

```http
HTTP/1.1 400 Bad Request

{
  "role": [
    "Registration always creates a buyer account. Use seller onboarding."
  ]
}
```

### 1.2 Log in

`POST /auth/login/` — public, throttled to 10/hour per IP. The username field is
the **email**.

```http
POST /auth/login/
Content-Type: application/json

{
  "email": "user_1@sample.harbourhub.com",
  "password": "password123"
}
```

```http
HTTP/1.1 200 OK

{
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": 2,
    "username": "user_1",
    "email": "user_1@sample.harbourhub.com",
    "full_name": "Ada Obi",
    "role": "buyer",
    "staff_role": null,
    "company": null,
    "phone": "08030000000",
    "location": "Lagos, Nigeria",
    "is_verified": false,
    "date_joined": "2026-10-29T12:00:00Z"
  }
}
```

A login with 2FA enabled does **not** return tokens:

```json
{
  "requires_2fa": true,
  "token": "eyJ1c2VyX2lkIjoyfQ:1a2b3c:...",
  "message": "Please complete 2FA verification."
}
```

Complete it with `POST /auth/2fa/verify/`, then log in again.

### 1.3 Refresh

`POST /auth/refresh/` — public.

```http
POST /auth/refresh/
Content-Type: application/json

{ "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." }
```

```json
{ "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." }
```

### 1.4 Sessions and "logout"

There is **no** `POST /auth/logout/` endpoint. Logout is one of:

1. Discard both tokens client-side (the default), or
2. Blacklist one session:

```http
DELETE /auth/sessions/14/
Authorization: Bearer <access>
```

```json
{ "message": "Session removed successfully." }
```

3. Blacklist every session except the current one:

```http
DELETE /auth/sessions/remove-all/
Authorization: Bearer <access>
```

```json
{ "message": "All other sessions removed." }
```

List sessions with `GET /auth/sessions/` (a bare array, not paginated; only
active sessions are returned):

```json
[
  {
    "id": 15,
    "device_name": "Windows PC",
    "device_type": "",
    "ip_address": "203.0.113.10",
    "is_active": true,
    "is_current": true,
    "last_active": "2026-10-31T09:20:00Z",
    "created_at": "2026-10-31T09:15:00Z"
  }
]
```

Removing a session sets `is_active` to `false` and blacklists its token when a
matching `OutstandingToken` exists.

Sessions also report a derived `device_type` (`mobile`, `desktop`, `tablet`). Older rows written
before the field existed derive it from the stored user agent instead of returning a blank string.

### 1.5 Public platform configuration

`GET /platform-config/` — no token required. Clients should read this before rendering marketplace
navigation so disabled listing types never appear.

```json
{
  "enable_buy": true,
  "enable_rent": true,
  "enable_services": true,
  "vendor_approval_required": false,
  "listing_approval_required": true,
  "default_currency": "NGN",
  "timezone": "Africa/Lagos",
  "date_format": "DD/MM/YYYY"
}
```

When a type is disabled, `POST /listings/` rejects it and public list/detail/recommendation/store
surfaces omit it. Example error:

```json
{ "error": "Buy listings are currently disabled." }
```

---

## 2. Seller onboarding, store, and listing

### 2.1 Promote the buyer

`POST /auth/become-seller/`

```json
{
  "business_name": "Blue Marine Supply",
  "phone": "08031234567",
  "country": "Nigeria"
}
```

```http
HTTP/1.1 200 OK

{
  "message": "Account upgraded to seller.",
  "next_step": "onboarding/step-1"
}
```

Calling it twice:

```http
HTTP/1.1 400 Bad Request

{ "error": "You are already a seller." }
```

### 2.2 Onboarding step 1 — store

`POST /auth/onboarding/step-1/`

```json
{
  "business_name": "Blue Marine Supply",
  "phone": "08031234567",
  "email": "sales@bluemarine.example",
  "country": "Nigeria"
}
```

```json
{
  "message": "Business details saved.",
  "store_id": 7,
  "store_slug": "blue-marine-supply",
  "next_step": "onboarding/step-2"
}
```

The store is created with `is_active: true`, `is_published: false`,
`is_verified: false`, and `commission_rate: "5.00"`. The slug is de-duplicated
with `-1`, `-2`, … when taken.

### 2.3 Onboarding step 2 — categories

`POST /auth/onboarding/step-2/`

```json
{ "category_ids": [3, 4] }
```

```json
{
  "message": "Categories saved.",
  "next_step": "onboarding/step-3"
}
```

Skipping step 1:

```http
HTTP/1.1 400 Bad Request

{ "error": "Please complete step 1 first." }
```

### 2.4 Onboarding step 3 — verification

`POST /auth/onboarding/step-3/` — `multipart/form-data`.

| Field | Type | Notes |
|---|---|---|
| `business_type` | choice | `sole_proprietorship`, `partnership`, `limited_liability`, `corporation`, `ngo` |
| `government_id` | file | ≤ 5 MB |
| `proof_of_registration` | file | ≤ 5 MB |
| `confirmed` | boolean | must be `true` |

```json
{
  "message": "Verification submitted. Your store setup request has been received. We will activate your store once verification is complete.",
  "next_step": "dashboard"
}
```

`GET /auth/onboarding/status/` reports progress:

```json
{
  "step_1_complete": true,
  "step_2_complete": true,
  "step_3_complete": true,
  "is_verified": false,
  "store_active": false,
  "current_step": 4
}
```

`store_active` is true only when the store is both active and published.

### 2.5 Create a listing

`POST /listings/` — multipart when images are included. The client never sends
`store`: the server resolves it from `request.user.store`. Sending `store` is
ignored because the field is read-only.

```http
POST /listings/
Authorization: Bearer <seller access>
Content-Type: multipart/form-data

title=Commercial Diving Helmet
description=Kirby Morgan-style helmet, serviced and pressure tested.
category=3
listing_type=sell
price=250000.00
currency=NGN
location=Lagos
country=Nigeria
state_province=Lagos
city=Lagos
contact_name=Blue Marine Supply
contact_email=sales@bluemarine.example
contact_phone=08031234567
condition=excellent
images_data=<binary>
```

```http
HTTP/1.1 201 Created

{
  "id": 42,
  "title": "Commercial Diving Helmet",
  "description": "Kirby Morgan-style helmet, serviced and pressure tested.",
  "category": 3,
  "store": 7,
  "listing_type": "sell",
  "price": "250000.00",
  "currency": "NGN",
  "price_unit": "",
  "negotiable": false,
  "location": "Lagos",
  "country": "Nigeria",
  "state_province": "Lagos",
  "city": "Lagos",
  "contact_name": "Blue Marine Supply",
  "contact_email": "sales@bluemarine.example",
  "contact_phone": "08031234567",
  "manufacturer": null,
  "model": null,
  "year": null,
  "condition": "excellent",
  "service_area": "",
  "status": "draft",
  "featured": false,
  "expires_at": null,
  "images": [
    {
      "id": 301,
      "image": "http://localhost:8000/media/listings/2026/10/helmet.jpg",
      "caption": "",
      "is_primary": true,
      "sort_order": 0
    }
  ],
  "documents": []
}
```

Without a store:

```http
HTTP/1.1 400 Bad Request

{ "store": ["Complete seller onboarding before creating a listing."] }
```

### 2.6 Publish

`POST /listings/42/publish/` — owner or admin only.

```json
{ "message": "Listing published successfully" }
```

Errors:

| Status | Body |
|---|---|
| `400` | `{"error": "Only draft listings can be published"}` |
| `400` | `{"error": "Listing cannot be published until its store is active."}` |
| `400` | `{"error": "Listings require admin approval before publishing."}` |
| `403` | `{"error": "Permission denied"}` |

Approval example. With `listing_approval_required = true`, a seller's create request is stored as
`draft` even when it asks for `published`, and publish is rejected until an admin approves it:

```http
POST /listings/
Content-Type: application/json

{
  "title": "Commercial Diving Helmet",
  "listing_type": "sell",
  "price": "250000.00",
  "status": "published"
}
```

```json
HTTP/1.1 201 Created

{
  "id": 42,
  "status": "draft",
  "published_at": null
}
```

```http
POST /listings/42/publish/
```

```json
HTTP/1.1 400 Bad Request

{ "error": "Listings require admin approval before publishing." }
```

When `listing_approval_required` is false, the same create request is published immediately.

### 2.7 Upload more images

`POST /listings/42/upload-images/` — multipart, repeated `images_data` fields.

Limits: 5 images per listing, 10 MB each, JPEG/PNG/WebP only.

```json
{ "message": "2 image(s) uploaded successfully" }
```

Failure examples:

```json
{ "error": "No images provided" }
{ "error": "A listing can have a maximum of 5 images. You currently have 4, trying to add 2." }
{ "error": "helmet.png exceeds the 10MB limit." }
{ "error": "helmet.gif is not an allowed image type (JPEG, PNG, WebP only)." }
```

---

## 3. Buy: cart → checkout → payment → earning

### 3.1 Add to cart with a delivery address

`POST /commerce/cart/items/`

Each cart item carries **its own** `delivery_detail`. There is no
checkout-level delivery address. The address must belong to the caller.

```json
{
  "listing": 42,
  "purchase_type": "buy",
  "quantity": 1,
  "delivery_detail": 11
}
```

```http
HTTP/1.1 201 Created

{
  "id": 88,
  "listing": 42,
  "listing_title": "Commercial Diving Helmet",
  "listing_price": "250000.00",
  "primary_image": "http://localhost:8000/media/listings/2026/10/helmet.jpg",
  "store": 7,
  "store_name": "Blue Marine Supply",
  "purchase_type": "buy",
  "quantity": 1,
  "duration_days": null,
  "unit_price": "250000.00",
  "subtotal": "250000.00",
  "locked_subtotal": null,
  "quote_request": null,
  "delivery_detail": 11,
  "created_at": "2026-10-31T09:25:00Z",
  "currency": "NGN",
  "currency_symbol": "₦"
}
```

The same `(cart, listing, purchase_type)` triple updates the existing row
instead of duplicating it.

Another user's address is rejected:

```http
HTTP/1.1 400 Bad Request

{ "delivery_detail": ["Delivery address not found."] }
```

Rent/lease without `duration_days`:

```json
{ "duration_days": ["duration_days is required for rent/lease."] }
```

### 3.2 View the cart

`GET /commerce/cart/`

```json
{
  "id": 19,
  "items": [
    {
      "id": 88,
      "listing": 42,
      "listing_title": "Commercial Diving Helmet",
      "listing_price": "250000.00",
      "primary_image": "http://localhost:8000/media/listings/2026/10/helmet.jpg",
      "store": 7,
      "store_name": "Blue Marine Supply",
      "purchase_type": "buy",
      "quantity": 1,
      "duration_days": null,
      "unit_price": "250000.00",
      "subtotal": "250000.00",
      "locked_subtotal": null,
      "quote_request": null,
      "delivery_detail": 11,
      "created_at": "2026-10-31T09:25:00Z"
    }
  ],
  "total": "250000.00",
  "item_count": 1,
  "updated_at": "2026-10-31T09:25:00Z",
  "currency": "NGN",
  "currency_symbol": "₦"
}
```

### 3.3 Checkout

`POST /commerce/checkout/`

```json
{
  "cart_item_ids": [88],
  "payment_method": "paystack",
  "terms_accepted": true
}
```

One cart item becomes one order. A checkout spanning two vendors returns two
orders but a single payment.

```http
HTTP/1.1 201 Created

{
  "message": "1 order(s) created.",
  "orders": [
    {
      "order_id": 101,
      "order_number": "ORD-4C1A9E7B2D3F",
      "total_amount": "250000.00"
    }
  ],
  "payments": [
    {
      "payment_id": 55,
      "reference": "PAY-9F3C2A7B1D4E5F60",
      "authorization_url": "https://checkout.paystack.com/abc123",
      "amount": "250000.00"
    }
  ]
}
```

At this point the order is `pending_payment`, the payment is `pending`, and the
cart item is deleted only after the gateway initialises successfully.

Notes:

- **Delivery fee comes from the seller's active shipping profile.** Checkout matches the
  cart item's delivery address city, then state, then country (case-insensitive) against the
  seller's active `ShippingProfile.zone_name`. A match adds that profile's `flat_rate_cost`
  once per cart line; no match adds `"0.00"`. A service listing or a line without an address is
  always free, and reaching `free_shipping_threshold` (in NGN) also makes the line free.
  Delivery is never commissionable.
- The price is converted to NGN once, and the order item snapshots
  `original_currency`, `original_unit_price`, and `exchange_rate`.
- The checkout request has no `delivery_detail_id`. The address comes from each
  cart item.

Delivery-fee worked example. The seller has an active profile with
`zone_name = "Lagos"`, `flat_rate_cost = "5000.00"`, and no free-shipping threshold. The
buyer's delivery address has `city = "Lagos"`:

```http
HTTP/1.1 201 Created

{
  "message": "1 order(s) created.",
  "orders": [
    {
      "order_id": 101,
      "order_number": "ORD-4C1A9E7B2D3F",
      "total_amount": "255000.00"
    }
  ],
  "payments": [
    {
      "payment_id": 55,
      "reference": "PAY-9F3C2A7B1D4E5F60",
      "authorization_url": "https://checkout.paystack.com/abc123",
      "amount": "255000.00"
    }
  ]
}
```

The resulting order stores `subtotal = "250000.00"`, `delivery_fee = "5000.00"`, and
`total_amount = "255000.00"`. A profile with `free_shipping_threshold = "300000.00"` would
instead produce `delivery_fee = "0.00"` for this line.

Failure modes:

```http
HTTP/1.1 400 Bad Request

{ "terms_accepted": ["You must accept the terms and conditions."] }
```

```json
{ "cart_item_ids": ["At least one cart item is required."] }
{ "non_field_errors": ["No valid cart items found."] }
{ "non_field_errors": ["Cart is empty."] }
{ "error": "These listings have no store and cannot be checked out: Helmet." }
```

Gateway down — the cart is **not** emptied:

```http
HTTP/1.1 502 Bad Gateway

{
  "error": "Payment gateway unavailable. Your cart is intact.",
  "payment_id": 55,
  "retry_url": "/commerce/checkout/session/30/retry/"
}
```

Retry with `POST /commerce/checkout/session/30/retry/`:

```json
{ "authorization_url": "https://checkout.paystack.com/def456" }
```

If the session is already paid:

```http
HTTP/1.1 400 Bad Request

{ "message": "Payment already successful" }
```

### 3.4 Paystack webhook

`POST /commerce/webhooks/paystack/` — public, no auth header. Paystack signs the
raw body with HMAC-SHA512 using `PAYSTACK_SECRET_KEY`; the hex digest must match
`x-paystack-signature`. `POST /commerce/payment/webhook/` is a deprecated alias that runs the
same view.

```http
POST /commerce/webhooks/paystack/
x-paystack-signature: 5d41402abc4b2a76b9719d911017c592...
Content-Type: application/json

{
  "event": "charge.success",
  "data": {
    "id": 3021456789,
    "reference": "PAY-9F3C2A7B1D4E5F60",
    "amount": 25000000,
    "status": "success"
  }
}
```

```json
{ "status": "ok" }
```

`amount` is in **kobo**. If it does not equal `payment.amount × 100`, the handler
raises and the endpoint returns `500 {"error": "handler failed"}` so Paystack
retries.

On success the server, in one transaction:

1. Marks the payment `success` and sets `paid_at`.
2. Moves each `pending_payment` order in the session to `paid`.
3. Snapshots `commission_rate` and `commission_amount` on the order.
4. Writes a `payment_confirmed` activity.
5. Accrues exactly one `VendorEarning`.
6. Applies a rental extension if the payment belongs to one.

Duplicate delivery returns `200` and does nothing:

```json
{ "status": "ok", "detail": "duplicate" }
```

Unknown event types are recorded as `ignored` and still return
`{"status": "ok"}`.

Invalid signature:

```http
HTTP/1.1 401 Unauthorized

{ "error": "Invalid signature" }
```

### 3.5 Verify from the client

`GET /commerce/payment/verify/PAY-9F3C2A7B1D4E5F60/`

After the webhook:

```json
{
  "status": "success",
  "message": "Payment confirmed.",
  "checkout_session_id": 30
}
```

Before the webhook, even when Paystack already reports success:

```json
{
  "status": "pending_confirmation",
  "message": "Awaiting webhook confirmation."
}
```

The webhook is the only path that finalises money. The verify endpoint never
marks a payment successful.

Other states:

```json
{ "status": "failed", "message": "Payment was not completed." }
{ "status": "pending", "message": "Payment not completed." }
```

```http
HTTP/1.1 503 Service Unavailable

{ "status": "unknown", "message": "Gateway unavailable. Try again shortly." }
```

### 3.6 The paid order

`GET /commerce/orders/101/`

```json
{
  "id": 101,
  "order_number": "ORD-4C1A9E7B2D3F",
  "buyer": 2,
  "seller": 3,
  "store": 7,
  "store_name": "Blue Marine Supply",
  "store_slug": "blue-marine-supply",
  "currency": "NGN",
  "subtotal": "250000.00",
  "delivery_fee": "0.00",
  "escrow_fee": "0.00",
  "total_amount": "250000.00",
  "status": "paid",
  "placed_at": "2026-10-31T09:30:00Z",
  "tracking_id": "",
  "delivery_address": "",
  "delivery_contact_name": "",
  "delivery_contact_phone": "",
  "delivery_carrier": "",
  "carrier": "",
  "order_items": [
    {
      "id": 240,
      "quote_request": null,
      "listing": 42,
      "listing_title": "Commercial Diving Helmet",
      "primary_image": "http://localhost:8000/media/listings/2026/10/helmet.jpg",
      "purchase_type": "buy",
      "quantity": 1,
      "unit_price": "250000.00",
      "subtotal": "250000.00",
      "rental_start_date": null,
      "rental_end_date": null,
      "duration_days": null,
      "pickup_scheduled_date": null,
      "delivery_detail": 11,
      "delivery_detail_data": {
        "id": 11,
        "contact_person": "Ada Obi",
        "address": "12 Marina Road",
        "city": "Lagos",
        "state": "Lagos",
        "country": "Nigeria",
        "phone": "08030000000"
      },
      "currency": "NGN",
      "currency_symbol": "₦"
    }
  ],
  "activities": [
    {
      "id": 900,
      "order": 101,
      "event_type": "payment_confirmed",
      "event_type_display": "Payment Confirmed",
      "message": "Payment confirmed.",
      "created_at": "2026-10-31T09:31:00Z"
    }
  ],
  "extra": {},
  "created_at": "2026-10-31T09:30:00Z",
  "updated_at": "2026-10-31T09:31:00Z",
  "currency": "NGN",
  "currency_symbol": "₦"
}
```

Commission snapshot for this order: rate `"5.00"`, amount `"12500.00"` — 5% of
the **goods subtotal**, not of delivery.

### 3.7 The earning and wallet

`GET /financials/earnings/`

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 64,
      "order": 101,
      "order_number": "ORD-4C1A9E7B2D3F",
      "listing": 42,
      "listing_title": "Commercial Diving Helmet",
      "listing_thumbnail": "http://localhost:8000/media/listings/2026/10/helmet.jpg",
      "listing_category": "Diving Equipment",
      "earning_type": "buy",
      "gross_amount": "250000.00",
      "commission_rate": "5.00",
      "commission_amount": "12500.00",
      "net_amount": "237500.00",
      "currency": "NGN",
      "status": "pending",
      "available_at": "2026-11-07T09:31:00Z",
      "created_at": "2026-10-31T09:31:00Z",
      "currency_symbol": "₦"
    }
  ]
}
```

`GET /financials/wallet/`

```json
{
  "id": 9,
  "pending_balance": "237500.00",
  "available_balance": "0.00",
  "total_withdrawn": "0.00",
  "currency": "NGN",
  "transactions": [
    {
      "id": 501,
      "transaction_type": "earning",
      "transaction_type_display": "Earning",
      "amount": "237500.00",
      "description": "Pending earning for order ORD-4C1A9E7B2D3F",
      "reference_id": "64",
      "created_at": "2026-10-31T09:31:00Z",
      "currency": "NGN",
      "currency_symbol": "₦"
    }
  ],
  "updated_at": "2026-10-31T09:31:00Z",
  "currency_symbol": "₦"
}
```

`GET /financials/earnings/summary/` (the real response shape, not the declared
schema):

```json
{
  "total_revenue": "0.00",
  "pending_balance": "237500.00",
  "available_balance": "0.00",
  "total_withdrawn": "0.00",
  "revenue_change_percent": 100.0,
  "currency": "NGN"
}
```

Release policy is 50/50:

- Day 7 after payment: 118,750.00 moves to available (earning becomes
  `partially_released`).
- On fulfilment: the remainder moves to available (earning becomes `available`).
- If the order fulfils before day 7, fulfilment releases the full net amount at
  once.

`VendorEarning.Status.PROCESSING` is defined but never entered by current code.

---

## 4. Fulfilment

The order state machine (from `apps/commerce/services/orders.py`):

```text
pending_payment → paid → order_confirmed → item_dispatched → in_transit
                → delivered → fulfilled
```

For rentals (`hire`/`lease` items) the tail is different:

```text
delivered → active_hire → hire_ended → item_returned → fulfilled
```

`draft` and `pending_payment` orders can be cancelled. `order_cancelled` is not
allowed from `paid` or later through the tracking endpoint; a paid order must be
refunded instead.

### 4.1 Seller marks shipped

`POST /commerce/orders/101/ship/`

```json
{
  "carrier": "DHL",
  "tracking_id": "DHL-88910022"
}
```

```json
{
  "message": "Order marked as shipped",
  "status": "item_dispatched",
  "carrier": "DHL",
  "tracking_id": "DHL-88910022"
}
```

Missing fields:

```json
{ "error": "carrier and tracking_id are required" }
```

### 4.2 Seller advances tracking

`POST /commerce/orders/101/tracking/update/`

The path accepts either the integer id or the order number.

```json
{
  "event": "in_transit",
  "note": "Departed Lagos hub."
}
```

The response is the tracking detail serializer:

```json
{
  "order_id": 101,
  "order_number": "ORD-4C1A9E7B2D3F",
  "status": "in_transit",
  "listing_title": "Commercial Diving Helmet",
  "buyer": { "name": "Ada Obi", "email": "user_1@sample.harbourhub.com" },
  "seller": { "name": "Blue Marine Supply", "store_slug": "blue-marine-supply" },
  "total_amount": "250000.00",
  "subtotal": "250000.00",
  "delivery_fee": "0.00",
  "escrow_fee": "0.00",
  "created_at": "2026-10-31T09:30:00Z",
  "estimated_delivery": "2026-11-07T09:30:00Z",
  "dispute": null,
  "timeline": [
    {
      "event": "order_placed",
      "label": "Order Placed",
      "description": "Order placed successfully.",
      "actor": "buyer",
      "actor_name": "Ada Obi",
      "timestamp": "2026-10-31T09:30:00Z",
      "is_current": false
    },
    {
      "event": "payment_confirmed",
      "label": "Payment Confirmed",
      "description": "Payment confirmed.",
      "actor": "system",
      "actor_name": null,
      "timestamp": "2026-10-31T09:31:00Z",
      "is_current": false
    },
    {
      "event": "item_dispatched",
      "label": "Item Dispatched",
      "description": "Dispatched via DHL. Tracking: DHL-88910022.",
      "actor": "seller",
      "actor_name": "Blue Marine Supply",
      "timestamp": "2026-10-31T10:00:00Z",
      "is_current": false
    },
    {
      "event": "in_transit",
      "label": "In Transit",
      "description": "Departed Lagos hub.",
      "actor": "seller",
      "actor_name": "Blue Marine Supply",
      "timestamp": "2026-10-31T14:00:00Z",
      "is_current": true
    }
  ],
  "tracking_id": "DHL-88910022",
  "delivery_carrier": "DHL",
  "currency": "NGN",
  "currency_symbol": "₦"
}
```

Allowed seller events: `order_confirmed`, `item_dispatched`, `in_transit`,
`delivered`, `hire_started`, `hire_ended`, `item_returned`, `order_fulfilled`,
`order_cancelled`.

An invalid event:

```json
{
  "error": "Invalid seller-triggered tracking event. Allowed events are: order_confirmed, item_dispatched, in_transit, delivered, hire_started, hire_ended, item_returned, order_fulfilled, order_cancelled"
}
```

An event the current status cannot perform:

```json
{ "error": "Cannot 'in_transit' an order in status 'paid'." }
```

A non-seller:

```http
HTTP/1.1 403 Forbidden

{ "detail": "Only the seller of this order can update the tracking status." }
```

### 4.3 Buyer confirms receipt

`POST /commerce/orders/101/confirm-receipt/` — buyer only, order must be
`delivered` (or `item_returned` for a rental).

```json
{
  "message": "Receipt confirmed",
  "status": "fulfilled"
}
```

This is also the point where the remaining held funds are released. For a
non-rental order confirmed before day 7, the vendor's whole net amount becomes
available immediately.

Only the buyer:

```http
HTTP/1.1 403 Forbidden

{ "detail": "Only the buyer can confirm receipt of this order." }
```

Wrong state:

```json
{ "error": "Cannot 'order_fulfilled' an order in status 'in_transit'." }
```

---

## 5. Rental extension (paid)

Extensions are per **item**, and the dates only move after payment. The old
per-order route returns a redirect-shaped error:

`POST /commerce/orders/101/extend-rental/`

```json
{
  "error": "Rentals are extended per item and require payment. Use the item endpoint.",
  "item_id": 240,
  "endpoint": "/commerce/orders/101/items/240/extend-rental/"
}
```

### 5.1 Create the extension

`POST /commerce/orders/101/items/240/extend-rental/`

Send either `duration_days` or `new_end_date`, not both.

```json
{ "duration_days": 3 }
```

```http
HTTP/1.1 201 Created

{
  "message": "Complete payment to extend the rental.",
  "extension_id": 12,
  "amount": "75000.00",
  "authorization_url": "https://checkout.paystack.com/ext789",
  "new_end_date": "2026-11-18"
}
```

Amount is `unit_price × quantity × additional_days`. The helmet above is a
buy item and cannot be extended; for a hire item priced at `25000.00` per day,
three extra days cost `75000.00`. The `new_end_date` is the item's current end
date plus those days.

Errors:

```json
{ "error": "This order cannot be extended yet." }
{ "error": "This item has no rental end date." }
{ "error": "duration_days must be an integer" }
{ "error": "duration_days must be positive" }
{ "error": "Invalid date format. Use YYYY-MM-DD" }
{ "error": "New end date must be after the current end date" }
{ "error": "The new end date must be in the future" }
{ "error": "duration_days or new_end_date is required" }
```

Gateway down (extension is cancelled):

```http
HTTP/1.1 502 Bad Gateway

{ "error": "Payment gateway unavailable." }
```

### 5.2 Pay and confirm

The response's `authorization_url` is a normal Paystack checkout for the
extension payment. When `charge.success` arrives with that payment's reference,
`finalize_payment` applies the extension exactly once:

- `OrderItem.rental_end_date` becomes the new end date.
- `OrderItem.duration_days` increases by the added days.
- The order subtotal, commission, and total are increased.
- A `rental_extended` activity is written.
- The vendor's pending balance is credited the extension's net amount.

The extension row moves from `pending_payment` to `paid`; the endpoint's
`extension_id` is how you correlate it. Paying twice does nothing because
`apply_rental_extension` returns early unless the status is
`pending_payment`.

---

## 6. Quote → counter-offer → cart

Quotes are for listings that need negotiation. Only **published** listings can
receive one.

### 6.1 Buyer requests a quote

`POST /commerce/quotes/`

```json
{
  "listing": 42,
  "store": 7,
  "purchase_type": "rent",
  "quantity": 1,
  "duration_days": 30,
  "preferred_delivery_date": "2026-11-10",
  "delivery_location": "Lagos",
  "delivery_detail": 11,
  "notes": "Need it for a 30-day survey."
}
```

```http
HTTP/1.1 201 Created

{
  "id": 71,
  "listing": 42,
  "listing_title": "Commercial Diving Helmet",
  "buyer": 2,
  "buyer_email": "user_1@sample.harbourhub.com",
  "store": 7,
  "store_name": "Blue Marine Supply",
  "store_slug": "blue-marine-supply",
  "purchase_type": "rent",
  "quantity": 1,
  "duration_days": 30,
  "preferred_delivery_date": "2026-11-10",
  "delivery_location": "Lagos",
  "delivery_detail": 11,
  "delivery_detail_data": {
    "id": 11,
    "contact_person": "Ada Obi",
    "address": "12 Marina Road",
    "city": "Lagos",
    "state": "Lagos",
    "country": "Nigeria",
    "phone": "08030000000"
  },
  "notes": "Need it for a 30-day survey.",
  "standard_price": "7500000.00",
  "adjustments": [],
  "total_quote_price": "7500000.00",
  "vendor_notes": "",
  "currency": "NGN",
  "status": "pending",
  "created_at": "2026-10-31T10:10:00Z",
  "updated_at": "2026-10-31T10:10:00Z",
  "currency_symbol": "₦"
}
```

`standard_price` is computed server-side: `price × quantity` for buy,
`price × quantity × duration_days` for rent/lease. It is read-only.

A draft listing:

```json
{ "listing": ["Listing must be published."] }
```

### 6.2 Vendor counter-offers

`PATCH /commerce/quotes/71/vendor-update/` — listing owner only.

```json
{
  "adjustments": [
    { "name": "Long-term discount", "amount": "500000.00", "type": "subtraction" }
  ],
  "vendor_notes": "Includes servicing and a spare mask."
}
```

```json
{
  "adjustments": [
    { "name": "Long-term discount", "amount": "500000.00", "type": "subtraction" }
  ],
  "vendor_notes": "Includes servicing and a spare mask."
}
```

`total_quote_price` becomes `7,000,000.00`. Adjustment types are `addition` and
`subtraction`; unknown types are ignored when computing the total.

### 6.3 Vendor responds

`POST /commerce/quotes/71/respond/`

The action route is `/commerce/quotes/{id}/{action}/` with `respond`, `cancel`,
`decline`, or `convert`. Actions are permission-checked by role.

```json
{ "message": "Quote responded successfully" }
```

The message is built as `f"Quote {action}ed successfully"`. In practice:

| Action | Message |
|---|---|
| `respond` | `Quote responded successfully` |
| `cancel` | `Quote canceled successfully` |
| `decline` | `Quote declineed successfully` (double `e`, a known wording bug) |
| `convert` | `Quote converted successfully` |

A non-owner trying to respond:

```http
HTTP/1.1 403 Forbidden

{ "error": "Only listing owner can respond" }
```

Only the buyer can cancel or decline:

```json
{ "error": "Only buyer can cancel" }
{ "error": "Only buyer can decline" }
```

Wrong state:

```json
{ "error": "Only pending quotes can be cancelled" }
{ "error": "Only pending quotes can be responded to" }
{ "error": "Only responded quotes can be converted" }
{ "error": "Cannot decline this quote" }
```

Unknown action:

```json
{ "error": "Invalid action" }
```

### 6.4 Buyer moves the quote to the cart

`POST /commerce/quotes/71/move-to-cart/`

```json
{ "quoted_price": "7000000.00" }
```

```json
{
  "message": "Quote moved to cart successfully.",
  "cart_item": {
    "listing": "Commercial Diving Helmet",
    "quantity": 1,
    "unit_price": "7000000.00"
  }
}
```

The cart item stores the agreed total in `locked_subtotal`; `unit_price` stays
the listing's original price. `locked_subtotal` wins over
`unit_price × quantity` when the cart total is computed. The quote becomes
`converted`, and checkout proceeds exactly as in section 3.

The endpoint only accepts quotes in `responded` state; anything else is a `404`
because the queryset filters on status.

---

## 7. Disputes

### 7.1 Buyer opens a dispute

`POST /commerce/disputes/`

```json
{
  "order": 101,
  "reason": "Item not as described",
  "description": "The regulator is missing and the valve leaks."
}
```

```http
HTTP/1.1 201 Created

{
  "id": 31,
  "order": 101,
  "order_number": "ORD-4C1A9E7B2D3F",
  "buyer": 2,
  "reason": "Item not as described",
  "description": "The regulator is missing and the valve leaks.",
  "status": "open",
  "status_display": "Open",
  "resolution_notes": "",
  "resolved_at": null,
  "created_at": "2026-11-01T08:00:00Z",
  "updated_at": "2026-11-01T08:00:00Z"
}
```

Opening a dispute freezes the order's earning (`is_disputed = true`) and writes
an activity. Frozen funds cannot be released or paid out.

`GET /commerce/disputes/` lists the caller's own disputes as buyer or seller;
admins see all. `GET /commerce/disputes/31/` retrieves one.

### 7.2 Admin resolves (vendor keeps the money)

`POST /commerce/disputes/31/action/` — requires the SUPPORTS admin module with
manage permission.

```json
{
  "action": "resolve",
  "resolution_notes": "Item matched the listing. No refund due."
}
```

```json
{ "message": "Dispute resolved. Funds released to vendor escrow." }
```

The dispute becomes `resolved`, `resolved_at` is set, the earning is unfrozen,
and an activity is written.

### 7.3 Admin refunds

```json
{
  "action": "refund",
  "resolution_notes": "Full refund approved."
}
```

```json
{
  "message": "Refund requested. The dispute closes when the gateway confirms."
}
```

The dispute becomes `under_review` while the gateway processes the refund. A
`refund.processed` webhook then:

- Marks the refund `processed`.
- Marks the payment `refunded` (or `partially_refunded`).
- Reverses the earning proportionally.
- Cancels the order and writes `order_refunded` for a full refund.

The dispute itself is **not** moved to `refunded` or `cancelled`: those statuses
exist but current code never sets them. This is residual debt, recorded in
[../data-model.md](../data-model.md).

No payment on the order:

```json
{ "error": "No payment is linked to this order." }
```

Invalid action:

```json
{ "error": "Invalid action." }
```

### 7.4 Refund webhook

```json
{
  "event": "refund.processed",
  "data": {
    "id": 99001122,
    "reference": "RF-7C2A9B4D1E60",
    "status": "processed"
  }
}
```

```json
{ "status": "ok" }
```

`refund.failed` marks the refund `failed` and returns `{"status": "ok"}`.

---

## 8. Money out: bank account → payout → transfer

### 8.1 Add a bank account

`POST /financials/bank-accounts/`

```json
{
  "account_name": "Blue Marine Supply",
  "account_number": "0123456789",
  "bank_name": "Sample Bank PLC",
  "bank_code": "058"
}
```

```http
HTTP/1.1 201 Created

{
  "id": 22,
  "account_name": "Blue Marine Supply",
  "account_number": "0123456789",
  "bank_name": "Sample Bank PLC",
  "bank_code": "058",
  "is_default": false,
  "is_verified": false,
  "created_at": "2026-11-01T08:10:00Z"
}
```

Account number must be exactly 10 digits:

```json
{ "account_number": ["Account number must be 10 digits."] }
{ "account_number": ["Account number must contain only digits."] }
```

Optional pre-check with Paystack:

`GET /financials/banks/resolve/?account_number=0123456789&bank_code=058`

```json
{ "account_name": "BLUE MARINE SUPPLY", "account_number": "0123456789" }
```

```json
{ "error": "Could not resolve account" }
```

Make it the default:

`POST /financials/bank-accounts/22/set-default/`

```json
{ "message": "Default bank account updated." }
```

### 8.2 Request a payout

`POST /financials/payouts/`

```json
{
  "amount": "100000.00",
  "bank_account": 22
}
```

```http
HTTP/1.1 201 Created

{
  "amount": "100000.00",
  "bank_account": 22
}
```

The create serializer returns only those two fields. Fetch
`GET /financials/payouts/` to see the full record, including `reference`,
`status`, `destination`, and `account_number`.

The request:

1. Locks the store wallet.
2. Checks `available_balance >= amount`.
3. Creates a `requested` payout with reference `PO-…`.
4. FIFO-allocates released earnings to it.
5. Decrements `available_balance` and writes a `payout` wallet transaction.
6. Queues `process_payout_task`, which creates a Paystack recipient and transfer.

Insufficient balance (checked by the serializer before the view runs):

```http
HTTP/1.1 400 Bad Request

{ "non_field_errors": ["Insufficient balance. Available: 0.00"] }
```

Zero or negative:

```json
{ "amount": ["Amount must be greater than zero."] }
```

No wallet for the account:

```json
{ "non_field_errors": ["Wallet not found."] }
```

Another user's bank account:

```json
{ "bank_account": ["Bank account does not belong to you."] }
```

### 8.3 Transfer webhook

Success:

```json
{
  "event": "transfer.success",
  "data": {
    "id": 77112233,
    "reference": "PO-2F7A9C1D4B60"
  }
}
```

```json
{ "status": "ok" }
```

This marks the payout `paid`, sets `processed_at`, adds to
`wallet.total_withdrawn`, and settles the allocated earnings (`paid_out` when
fully paid).

Failure or reversal:

```json
{
  "event": "transfer.failed",
  "data": {
    "id": 77112234,
    "reference": "PO-2F7A9C1D4B60",
    "reason": "Recipient account is invalid"
  }
}
```

The payout becomes `failed`, its allocations are removed, and the amount is
re-credited to `available_balance`.

An unknown payout reference is ignored (recorded as `ignored`) and still
returns `{"status": "ok"}`.

---

## 9. Notifications

In-app notifications are exposed over HTTP. Preferences and delivery attempts
are **not** exposed; they are internal records.

### 9.1 List and count

`GET /notifications/` — paginated, filterable by `is_read`,
`notification_type`, and `priority`.

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 480,
      "notification_type": "order_paid",
      "title": "Payment received",
      "message": "Your payment for ORD-4C1A9E7B2D3F was confirmed.",
      "priority": "high",
      "action_url": "/orders/101",
      "action_label": "View order",
      "related_object_type": "order",
      "related_object_id": 101,
      "is_read": false,
      "read_at": null,
      "created_at": "2026-10-31T09:31:00Z"
    }
  ]
}
```

`GET /notifications/count/`

```json
{ "total": 12, "unread": 3 }
```

### 9.2 Read and delete

| Call | Result |
|---|---|
| `POST /notifications/480/read/` | `{"message": "Notification marked as read."}` |
| `POST /notifications/read-all/` | `{"message": "3 notification(s) marked as read."}` |
| `DELETE /notifications/480/` | `204 No Content` |
| `DELETE /notifications/clear/` | `204 No Content` |

Missing or someone else's notification:

```http
HTTP/1.1 404 Not Found

{ "error": "Notification not found." }
```

### 9.3 Delivery channels

Creating a notification also queues out-of-band deliveries. Every channel is supported and
returns `sent` or `skipped` with a truthful reason; none raises into the request:

| Channel | Adapter | Notes |
|---|---|---|
| `in_app` | the `Notification` row itself | always on for transactional events |
| `email` | `channels.send_email` | Django email backend |
| `sms` | `channels.send_sms` | Termii only; `SMS_PROVIDER=termii` and `TERMII_API_KEY` |
| `push` | `channels.send_push` | VAPID web push; gone endpoints are deactivated |
| `staff_webhook` | `channels.send_staff_webhook` | posts JSON to `OPS_WEBHOOK_URL` |

`NotificationPreference` decides which channels are allowed per category, but transactional
in-app and email are always on. `NotificationDelivery` records each attempt with `queued`,
`sent`, `failed`, or `skipped`. Preferences and deliveries are inspectable in the Django admin.

### 9.4 Notification preferences

`GET /notifications/preferences/` returns the three categories in declared order:

```json
[
  {
    "id": 1,
    "category": "transactional",
    "in_app": true,
    "email": true,
    "sms": false,
    "push": true
  },
  {
    "id": 2,
    "category": "messages",
    "in_app": true,
    "email": true,
    "sms": false,
    "push": true
  },
  {
    "id": 3,
    "category": "marketing",
    "in_app": true,
    "email": false,
    "sms": false,
    "push": false
  }
]
```

`PATCH /notifications/preferences/marketing/` with `{"email": true}` updates one category.
Turning off transactional in-app or email is rejected:

```json
{ "error": "Transactional in-app and email notifications cannot be disabled." }
```

### 9.5 Browser push subscription

1. Read the application server key:

   `GET /notifications/push/public-key/`

   ```json
   { "public_key": "BEl...", "configured": true }
   ```

2. After the browser's `pushManager.subscribe(...)` resolves, register the endpoint:

   ```json
   POST /notifications/push/subscriptions/
   Authorization: Bearer <access>

   {
     "endpoint": "https://fcm.googleapis.com/fcm/send/abc",
     "keys": { "p256dh": "BN...", "auth": "k..." },
     "user_agent": "Mozilla/5.0 ..."
   }
   ```

   ```json
   HTTP/1.1 201 Created

   {
     "id": 9,
     "endpoint": "https://fcm.googleapis.com/fcm/send/abc",
     "is_active": true,
     "created_at": "2026-11-02T10:00:00Z"
   }
   ```

   Registering the same endpoint again updates its keys and reactivates it. An endpoint owned
   by another account returns `400`.

3. Remove it with `DELETE /notifications/push/subscriptions/9/` (`204`), or list your
   subscriptions with `GET /notifications/push/subscriptions/`.

---

## 10. Cross-cutting error shapes

| Status | Shape | When |
|---|---|---|
| `400` | `{"field": ["message"]}` | DRF serializer validation |
| `400` | `{"error": "..."}` | Explicit view validation |
| `401` | `{"detail": "Authentication credentials were not provided."}` | Missing/expired token |
| `403` | `{"detail": "You do not have permission to perform this action."}` | Permission class |
| `404` | `{"detail": "Not found."}` | Missing object or filtered queryset |
| `405` | `{"detail": "Method \"GET\" not allowed."}` | Wrong verb |
| `429` | `{"detail": "Request was throttled. Expected available in N seconds."}` | Throttle |
| `500` | `{"error": "handler failed"}` | Webhook handler exception |
| `502` | `{"error": "Payment gateway unavailable. Your cart is intact."}` | Paystack init failure |
| `503` | `{"status": "unknown", "message": "Gateway unavailable. Try again shortly."}` | Verify during an outage |

Unpaid order cancellation (`POST /commerce/orders/{id}/cancel/`):

```json
{ "message": "Order cancelled successfully" }
```

Cancelling a **paid** order is a refund request. It returns `202 Accepted`:

```json
{
  "message": "Refund requested. The order will be cancelled once the gateway confirms.",
  "refund_id": 18,
  "refund_status": "pending"
}
```

An order that is already dispatched or later:

```json
{ "error": "Order cannot be cancelled at this stage" }
```

The exact wording for every domain message is in [messages.md](messages.md).
