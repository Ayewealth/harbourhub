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

The documentation index for the whole repository is [`../README.md`](../README.md).

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

Operations marked **Public** in the [endpoint reference](endpoints.md) need no header. These are
registration and login (including OTP, password reset, social login, and the 2FA login step-up), the
public platform-config, listing, store, category, review, career, search, and shipping-option reads,
page feedback, support contact, the admin-invite acceptance, the push public key, and both Paystack
webhook paths. Every other operation requires a bearer token, and webhooks additionally require a
valid signature.

A token supplied to a public read is still honoured where it can change the result: listing detail
includes the caller's own non-public listings and global search records the caller's search
history. All other public operations ignore it.

| Step | Endpoint | Notes |
|---|---|---|
| Register | `POST /auth/register/` | Always creates a **buyer**. Sending `role` other than `buyer` returns `400`. |
| Login | `POST /auth/login/` | Body: `{"email": "...", "password": "..."}`. Returns `access`, `refresh`, and `user`. |
| Refresh | `POST /auth/refresh/` | Body: `{"refresh": "..."}`. Rotation is enabled and the old token is blacklisted. |
| Logout | no dedicated route | Discard both tokens client-side, or blacklist a session with `DELETE /auth/sessions/{id}/` (current or another of your sessions) or `DELETE /auth/sessions/remove-all/` (all except the current one). |
| OTP request | `POST /auth/otp/request/` | Body: `{"email": "...", "purpose": "registration"}`. |
| OTP verify | `POST /auth/otp/verify/` | Body: `{"email": "...", "code": "123456", "purpose": "registration"}`. |
| Set password | `POST /auth/set-password/` | Completes an OTP-first registration. |
| Social login (Google) | `POST /auth/social/google/` | Body: `{"id_token": "..."}` or `{"access_token": "..."}`. Returns the same tokens as login. |
| Social login (Apple) | `POST /auth/social/apple/` | Body: `{"id_token": "..."}`. Returns the same tokens as login. |

Social login is disabled with `503` until `GOOGLE_CLIENT_ID` / `APPLE_CLIENT_ID` is configured.
Both providers require a verified email address owned by this application's client id.

### Public platform configuration

`GET /platform-config/` is unauthenticated and returns the switches that shape the public
marketplace:

```json
{
  "enable_buy": true,
  "enable_rent": true,
  "enable_services": true,
  "vendor_approval_required": false,
  "listing_approval_required": false,
  "default_currency": "NGN",
  "timezone": "Africa/Lagos",
  "date_format": "DD/MM/YYYY"
}
```

The flags are enforced server-side: disabled listing types cannot be created or read publicly,
`listing_approval_required` makes seller listings wait in `draft`, and
`vendor_approval_required` controls whether a verification request is reviewed or auto-approved.

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
- **Ids.** Integer `id` values are the API keys. Order responses also expose `order_id`, an alias
  of `id` used by the orders page for detail fetches. `order_number` is display-only and appears
  only in list responses. `reference` and slugs are display-only unless an endpoint explicitly
  accepts them.
- **Dates.** ISO 8601. Date-only fields use `YYYY-MM-DD`; timestamps are UTC.
- **Order list rows.** `GET /commerce/orders/my-orders/` and `/commerce/orders/store-orders/`
  return a lightweight summary per order: `order_id`, `order_number`, `status`, `total_amount`,
  `currency`, `quantity` (total units across the order's items), `listing_title`, `seller_name`,
  `buyer_name`, `last_event`, `last_event_at`, `tracking_id`, and `delivery_carrier`.
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

- Payment success is confirmed by the Paystack webhook
  (`POST /commerce/webhooks/paystack/`), not by the client.
  `POST /commerce/payment/webhook/` remains as a deprecated alias for existing dashboard
  configurations. `GET /commerce/payment/verify/{reference}/` is a **read-only** status poller.
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

## Notification channels

Every notification is written in-app and then fanned out to the recipient's preferences:

| Channel | Adapter | Configured by | When unconfigured |
|---|---|---|---|
| In-app | `Notification` row | Always on | — |
| Email | Django email backend / Celery task | `EMAIL_*` | Skipped when unset |
| SMS | Termii | `SMS_PROVIDER=termii` + `TERMII_API_KEY` | Skipped when unset |
| Web push | VAPID + `pywebpush` | `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` (PEM path) / `VAPID_SUBJECT` | Skipped when unset |
| Staff webhook | JSON POST to operations | `OPS_WEBHOOK_URL` | Skipped when unset |

`GET /notifications/preferences/` returns `transactional`, `messages`, and `marketing` in that
order. `PATCH /notifications/preferences/{category}/` updates one category; transactional
in-app and email cannot be disabled. `GET /notifications/push/public-key/` returns the VAPID
public key and whether push is configured. Registered browser endpoints are managed through
`/notifications/push/subscriptions/`.

## Route aliases

The canonical routes come first; aliases remain so no client breaks:

| Canonical | Deprecated alias |
|---|---|
| `POST /commerce/webhooks/paystack/` | `POST /commerce/payment/webhook/` |
| `GET /analytics/` | `GET /analytics/analytics/` |
| `GET /quotes/sent/`, `GET /quotes/received/` | `GET /commerce/quotes/sent/`, `GET /commerce/quotes/received/` |

The generated [endpoint reference](endpoints.md) lists the canonical path first. The webhook alias is
also marked deprecated in the OpenAPI schema; the analytics and quote aliases remain documented here
because they reuse the canonical view.

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
