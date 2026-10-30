# Harbour Hub API

The Harbour Hub REST API serves the buyer, seller, and staff clients. This directory is the
human-readable companion to `schema.yml`, the OpenAPI 3.0 contract that drives the interactive
docs.

| Document | What it answers |
|---|---|
| [`endpoints.md`](endpoints.md) | Every path, method, operation id, auth requirement, request body, and response code. Generated from `schema.yml`. |
| [`messages.md`](messages.md) | Every success and error message the API can return, with its status code and trigger. |
| [`examples.md`](examples.md) | End-to-end request/response walkthroughs for the core flows. |
| [`../data-model.md`](../data-model.md) | Entities, relationships, status machines, and the money invariants. |
| [`../sample-data.md`](../sample-data.md) | The deterministic sample dataset and how to seed it safely. |
| [`../../schema.yml`](../../schema.yml) | The OpenAPI contract itself. |

Interactive documentation is served by the application:

| URL | UI |
|---|---|
| `/api/schema/` | Raw OpenAPI document |
| `/api/docs/` | Swagger UI |
| `/api/redoc/` | ReDoc |

---

## Base URL and versioning

The application mounts the API at the site root; the deployment may add an `/api/v1` prefix at
the gateway. The schema declares two servers:

| Environment | Base URL |
|---|---|
| Production | `https://api.harbourhubglobal.com` |
| Local | `http://localhost:8000` |

Every path in `endpoints.md` is relative to that base. The document version comes from
`API_VERSION` (`1.0.0` by default; local `.env` may set `v1`). Breaking changes require a new
major version.

---

## Authentication

The API uses JWT bearer tokens from `djangorestframework-simplejwt`.

```http
Authorization: Bearer <access_token>
```

| Step | Endpoint | Notes |
|---|---|---|
| Register | `POST /auth/register/` | Always creates a **buyer**. Sending `role` other than `buyer` returns `400`. |
| Login | `POST /auth/login/` | Body: `{"email": "...", "password": "..."}`. Returns `access`, `refresh`, and `user`. |
| Refresh | `POST /auth/refresh/` | Body: `{"refresh": "..."}`. Rotation is enabled and the old token is blacklisted. |
| Logout | `POST /auth/logout/` | Blacklists the supplied refresh token. |
| OTP request | `POST /auth/otp/request/` | Body: `{"email": "...", "purpose": "registration"}`. |
| OTP verify | `POST /auth/otp/verify/` | Body: `{"email": "...", "code": "123456", "purpose": "registration"}`. |
| Set password | `POST /auth/set-password/` | Completes an OTP-first registration. |

A successful login returns:

```json
{
  "access": "<jwt>",
  "refresh": "<jwt>",
  "user": {
    "id": 42,
    "username": "ada",
    "email": "ada@example.com",
    "full_name": "Ada Okafor",
    "role": "buyer",
    "staff_role": null,
    "company": "Ada Marine",
    "phone": "+2348012345678",
    "location": "Lagos",
    "is_verified": false,
    "date_joined": "2026-10-30T08:00:00Z"
  }
}
```

If the account has 2FA enabled, the same endpoint returns `200` with a short-lived signed token
instead of JWTs:

```json
{
  "requires_2fa": true,
  "token": "<signed-user-token>",
  "message": "Please complete 2FA verification."
}
```

Complete it with `POST /auth/2fa/verify/` using `{"token": "...", "code": "123456"}`.

### Roles

| Role | Meaning |
|---|---|
| `buyer` | Default. Can shop, quote, order, review, and open disputes. |
| `seller` | Owns a store; can publish listings and fulfil orders. |
| `service_provider` | Can own a store and sell services. |
| `admin` | Staff dashboard role. |
| `super_admin` | Full staff access. |

Registration cannot set a privileged role. Seller promotion happens through
`POST /auth/become-seller/`, followed by the three onboarding steps.

---

## Request and response conventions

- **JSON only.** Send `Content-Type: application/json` except for image uploads, which use
  `multipart/form-data`.
- **Snake case.** Field names are `snake_case` in both directions.
- **Ids.** Integer `id` values are the API keys. `order_number`, `reference`, and slugs are
  display-only unless an endpoint explicitly accepts them.
- **Dates.** ISO 8601. Date-only fields use `YYYY-MM-DD`; timestamps are UTC.
- **Money.** Decimal strings with two places, for example `"205000.00"`. See [Money](#money).

### Pagination

List endpoints use page-number pagination:

```json
{
  "count": 57,
  "next": "https://api.example.com/commerce/orders/?page=2",
  "previous": null,
  "results": []
}
```

`PAGE_SIZE` defaults to 20 and is configurable through `DEFAULT_PAGE_SIZE`. Request a page with
`?page=2`.

### Filtering, search, and ordering

Most list endpoints use `django-filter`, `SearchFilter`, and `OrderingFilter`. The generated
endpoint reference lists the parameters each operation accepts. Common patterns:

- `?search=excavator` — free-text search where the view declares `search_fields`.
- `?ordering=-created_at` — order by a declared field; prefix `-` for descending.
- `?status=published` — exact-match filter declared by the view's filterset.
- `?page_size=` is **not** enabled globally; use `PAGE_SIZE` or a dedicated endpoint.

### Errors

There are two error shapes.

**Validation errors** use DRF's field map and return `400`:

```json
{
  "email": ["Enter a valid email address."],
  "password_confirm": ["Password confirmation doesn't match."]
}
```

**Business-rule errors** use a single `error` string and return the status that matches the
failure:

```json
{"error": "Only the buyer can cancel this order."}
```

Some endpoints return a `message` with a success status, and a few return both `message` and
`error` keys on different branches. The complete catalogue, including exact strings and status
codes, is in [`messages.md`](messages.md).

| Status | Meaning |
|---|---|
| `200` | Success with a body. |
| `201` | Resource created. |
| `202` | Accepted; an asynchronous action (for example a refund) is pending. |
| `204` | Success with no body. |
| `400` | Validation or business-rule failure. |
| `401` | Missing, expired, or invalid token; invalid webhook signature. |
| `403` | Authenticated but not allowed (wrong role, not the owner, no admin module). |
| `404` | Object not found or not visible to this user. |
| `405` | Method not allowed on that route. |
| `429` | Throttled. |
| `500` | Unhandled server error. |
| `502` | Payment or transfer gateway failed. |
| `503` | Gateway unreachable; retry shortly. |

### Rate limits

| Scope | Default |
|---|---|
| Anonymous | `100/hour` per IP (`API_RATE_LIMIT`) |
| Authenticated | `1000/hour` per user (`API_RATE_LIMIT`) |
| Burst | `100/minute` (`API_BURST_LIMIT`) |
| Login | `10/hour` per IP |

Throttled responses return `429` with DRF's `{"detail": "Request was throttled..."}` body.

---

## Money

- All stored monetary columns are **Decimal NGN**. No float is used on a money path.
- The buyer pays `subtotal + delivery_fee`. There is no escrow fee, service fee, or platform fee
  on the buyer side.
- The platform earns a **seller commission** on goods only:
  `commission = round(subtotal × commission_rate / 100)`. Delivery passes to the vendor in full.
- Commission and currency rates are **snapshotted** on the order at payment time. A later rate
  change never rewrites history.
- Foreign listing prices are converted once at checkout. `OrderItem` stores
  `original_currency`, `original_unit_price`, and `exchange_rate` (NGN per unit).
- Display conversion is separate: send `hh_currency` as a cookie or `hh-currency` header, or set
  the user preference, and read `currency` / `currency_symbol` in list responses. Display
  conversion never changes stored money.

Worked example (₦100,000 item × 2, ₦5,000 delivery, 5% commission):

| Line | Amount |
|---|---|
| Goods subtotal | ₦200,000.00 |
| Delivery | ₦5,000.00 |
| **Buyer pays** | **₦205,000.00** |
| Platform commission (5% of goods) | ₦10,000.00 |
| **Vendor net** | **₦195,000.00** |

Earnings release in two tranches: 50% at day 7, the remainder when the order is fulfilled. See
[`../data-model.md`](../data-model.md).

---

## Status enums

| Enum | Values |
|---|---|
| `Order.Status` | `draft`, `pending_payment`, `paid`, `order_confirmed`, `item_dispatched`, `in_transit`, `delivered`, `active_hire`, `hire_ended`, `item_returned`, `fulfilled`, `cancelled` |
| `Payment.Status` | `pending`, `success`, `failed`, `partially_refunded`, `refunded` |
| `Refund.Status` | `pending`, `processed`, `failed` |
| `QuoteRequest.Status` | `pending`, `responded`, `cancelled`, `converted` |
| `Dispute.Status` | `open`, `under_review`, `resolved`, `refunded`, `cancelled` |
| `RentalExtension.Status` | `pending_payment`, `paid`, `cancelled` |
| `CartItem.PurchaseType` | `buy`, `rent`, `lease` |
| `VendorEarning.Status` | `pending`, `partially_released`, `available`, `processing`, `paid_out`, `reversed` |
| `Payout.Status` | `requested`, `processing`, `paid`, `failed`, `frozen` |
| `Listing.Status` | `draft`, `published`, `paused`, `archived`, `flagged`, `suspended` |
| `VerificationRequest.Status` | `pending`, `approved`, `rejected`, `requires_more_info` |
| `SupportTicket.Status` | `open`, `in_progress`, `resolved`, `closed` |
| `Inquiry.Status` | `pending`, `read`, `replied`, `closed`, `spam` |
| `ComplianceDocument.Status` | `active`, `expiring`, `expired`, `rejected`, `included`, `pending` |

---

## Payments and webhooks

- Payment success is confirmed by the Paystack webhook (`POST /commerce/payment/webhook/`), not by
  the client. `GET /commerce/payment/verify/{reference}/` is a **read-only** status poller.
- The webhook verifies `x-paystack-signature`, writes a `WebhookEvent` row keyed by
  `(provider, event_type, gateway_event_id)`, and returns `200` for a duplicate without
  reprocessing.
- Supported events: `charge.success`, `charge.failed`, `refund.processed`, `refund.failed`,
  `transfer.success`, `transfer.failed`, `transfer.reversed`.
- A transient failure returns `500` so Paystack retries. A permanent failure is logged, marked
  `ignored`, and returns `200`.
- `finalize_payment` is idempotent; a second webhook or a reconciliation run cannot double-credit.
- `reconcile_pending_payments_task` is the safety net for a lost webhook.

---

## Regenerating the contract

```powershell
python manage.py spectacular --file schema.yml
python manage.py spectacular --file schema.yml --validate
python scripts/generate_api_reference.py
```

`--validate` checks the document; run the write command first because the validate pass can emit
the file before the root `servers`/`tags` sections are attached. Commit `schema.yml` and
`docs/api/endpoints.md` together whenever the API surface changes.
