# Harbour Hub P5 - Zero-Debt Alignment Design

> **Status:** draft for review
> **Date:** 2026-11-02
> **Predecessors:** `P0-COMPLETE.md` through `P4-COMPLETE.md`
> **Supersedes:** the post-P4 debt list in `docs/superpowers/plans/P4-COMPLETE.md`
> **Branch:** `main`

---

## 1. Context

P0-P4 closed the known correctness, money, performance and documentation debt, but a
fresh audit found work that was never recorded in the phase records:

- code paths that exist but are never reachable (`VendorEarning.PROCESSING`,
  `Dispute.REFUNDED`, `Dispute.CANCELLED`);
- endpoints that return misleading data (`AdminAnalyticsExportView` returns hardcoded
  numbers);
- schema declarations that do not match their responses (`EarningsSummarySerializer`);
- a checkout that always writes `delivery_fee = 0.00` even though sellers configure
  shipping profiles;
- an invoice that prints `Escrow Fee:` and never renders the delivery block;
- notification push that is a stub, and notification preferences that have no HTTP
  surface;
- Google/Apple social login routes that are undocumented and weakly verified;
- an almost-empty Django admin for the most important business models;
- stale, misleading documentation (`figma-backend-gap-checklist.md`, the root README);
- configuration, dependency, CI and deployment drift.

This phase makes the repository, the running contract and the documentation describe the
same system. It does not add new product lines.

### 1.1 User decisions already made

| Decision | Choice |
|---|---|
| Phase scope | Reconcile and finish existing features only. Ads, premium users, realtime WebSockets and a mobile app stay a documented future backlog. |
| Delivery fee | Match the seller's active `ShippingProfile` zone to the buyer's delivery state/city; apply the free-shipping threshold; no match means `0.00`. |
| Unused statuses | Wire `VendorEarning.PROCESSING`, `Dispute.REFUNDED` and `Dispute.CANCELLED` into real flows. |
| Push transport | Web Push with VAPID (`pywebpush`), not FCM. |
| Social login | Keep and harden Google/Apple; do not remove. |
| `New_Feautures.docx` | Transcribe to Markdown under `docs/product/`, then delete the binary. |
| Figma checklist | Rewrite as an accurate coverage map, keeping the frame links. |
| Route cleanup | Canonical route plus a deprecated alias. |
| SMS provider | Termii only; remove the unusable Twilio branch. |
| Local S3 CSVs | Leave them; only confirm they are ignored and were never committed. |

### 1.2 Six additional requirements

1. Public read-only `GET /platform-config/` returning `enable_buy`, `enable_rent`,
   `enable_services`, `vendor_approval_required`, `listing_approval_required`,
   `default_currency`, `timezone`, `date_format`.
2. Enforce `listing_approval_required` (draft vs published) and auto-assign
   `Listing.store = request.user.store` on `POST /listings/`.
3. Run a one-time backfill linking store-less listings to `owner.store`.
4. Enforce `vendor_approval_required` in `POST /auth/verification/request/`; when false,
   auto-approve the verification and the store.
5. Enforce `enable_buy`, `enable_rent` and `enable_services` on `POST /listings/` and
   public `GET /listings/`.
6. On the production server, replace the Paystack test keys with live keys and register
   the live webhook URL `https://api.harbourhubglobal.com/commerce/webhooks/paystack/`.

---

## 2. Goals

1. Every defined status is reachable, or removed.
2. Every declared response field exists; every returned field is declared.
3. Every configured channel (in-app, email, SMS, push, staff webhook) actually works.
4. Every business model that staff need to operate is manageable in the Django admin.
5. Every configuration variable used by the code is documented, and every documented
   variable is used.
6. The CI, deploy and build scripts match the documented runtime.
7. Public configuration is readable without authentication, and it actually changes
   listing behaviour.
8. Documentation matches the code, including known limitations.
9. No existing business data is deleted or rewritten.

## 3. Non-goals

- Advertisements and premium users from `New_Feautures.docx`. They become
  `docs/product/future-backlog.md`.
- Realtime WebSockets; the REST messaging surface stays.
- Firebase Cloud Messaging, native mobile apps, or multi-language support.
- Buyer-side fees. Buyers continue to pay no platform fee; commission is seller-side.
- A redesign of the seller onboarding flow beyond the approval flag.
- Changing the existing Paystack test-mode test suite; only the production credentials
  and webhook registration change.

---

## 4. Design

### 4.1 Platform configuration

#### 4.1.1 Public endpoint

`GET /platform-config/`

- Authentication: none (`AllowAny`).
- Returns a stable subset of the singleton `PlatformConfig` row:

```json
{
  "enable_buy": true,
  "enable_rent": true,
  "enable_services": false,
  "vendor_approval_required": true,
  "listing_approval_required": true,
  "default_currency": "NGN",
  "timezone": "Africa/Lagos",
  "date_format": "DD/MM/YY"
}
```

- Uses `PlatformConfig.get()` so the row is created on first call.
- `Cache-Control: public, max-age=60` to keep it cheap on the public home page.
- The existing admin endpoint `GET/PATCH /admin-panel/dashboard/config/` stays the way
  staff change values.
- No security, session, admin-notification or force-password-reset fields are exposed.

#### 4.1.2 Enforcement points

`PlatformConfig` is read once per request in the affected views. No caching layer is
introduced in this phase.

### 4.2 Listings

#### 4.2.1 Store assignment

`ListingCreateUpdateSerializer` already derives `store` from `request.user.store` and
declares `store` as read-only. P5 makes this explicit and permanent:

- `POST /listings/` with no store returns the existing
  `{"store": ["Complete seller onboarding before creating a listing."]}`.
- A client-supplied `store` is ignored; it can never select another vendor's store.
- Regression tests prove the store is the authenticated owner's store and that a
  forged `store` value is ignored.

#### 4.2.2 Enabled marketplace types

The config flags map to listing types:

| Config | Listing types |
|---|---|
| `enable_buy` | `sell` |
| `enable_rent` | `rent`, `lease` |
| `enable_services` | `service` |

**Create** (`POST /listings/`): a disabled `listing_type` returns `400` with:

- `{"listing_type": ["Buy listings are currently disabled."]}`
- `{"listing_type": ["Rent and lease listings are currently disabled."]}`
- `{"listing_type": ["Service listings are currently disabled."]}`

**Update** (`PATCH /listings/{id}/`): the check applies only when `listing_type` is
supplied and changes to a disabled type. Editing other fields of an existing
disabled-type listing stays allowed, so a config change never freezes old records.

Validation happens before any file or row is written.

**Public read** (`GET /listings/`, `GET /listings/{id}/`, top deals, best reviewed,
global search, public store detail and public store listing counts, category counts):

- Listings whose type is disabled are excluded from every public queryset and count.
- A single helper in `apps/listings/public.py` computes the enabled-type `Q` and is used
  by every public surface, so the rule cannot drift.
- `GET /listings/{id}/` for a disabled type returns `404` to the public, while the
  owner and admins can still retrieve it.
- Seller-facing lists (`my_listings`) and admin lists are not filtered.
- Existing carts, quotes and orders are not invalidated: the flags control discovery and
  new listing creation, not in-flight transactions.

#### 4.2.3 Listing approval

`listing_approval_required` controls whether a seller may publish directly.

Seller-supplied statuses are first restricted to the owner-controlled set
(`draft`, `published`, `paused`, `archived`). `flagged` and `suspended` always return
`400 {"status": ["This status can only be set by an administrator."]}`.

**Create**

- `listing_approval_required=True`:
  - an omitted status becomes `draft`;
  - `draft` stays `draft`;
  - `published`, `paused` and `archived` are stored as `draft`.
- `listing_approval_required=False`:
  - an omitted status becomes `published`;
  - `draft`, `published`, `paused` and `archived` are honoured as requested.
- Admins may set any status.
- `published_at` is set by the model save hook only when the final status is
  `published`.
- Pending listings appear in the existing admin listing list; no new notification is
  added.

**Update**

- `listing_approval_required=True`:
  - `published` is allowed only when the listing was already approved before
    (`published_at` is not null) and its current status is `draft`, `paused` or
    `published` (re-publishing a withdrawn or edited approved listing).
  - a never-published draft returns
    `400 {"status": ["Listings require admin approval before publishing."]}`.
  - `draft`, `paused` and `archived` are allowed.
- `listing_approval_required=False`: `draft`, `published`, `paused` and `archived` are
  accepted.
- Admins bypass these rules.

**Status actions** (`POST /listings/{id}/publish/`, `resume/`, `pause/`, `archive/`)

These bypass the serializer today, so the approval rule is enforced here too:

- `publish`: when `listing_approval_required=True` and `published_at` is null, a
  non-admin gets `400 {"error": "Listings require admin approval before publishing."}`;
  admins may publish. When the flag is false, the existing behaviour is unchanged.
- `resume`: a paused listing already has `published_at`, so resuming stays allowed.
- `pause` and `archive`: unchanged.

**Django admin bulk action**

`ListingAdmin.mark_published` currently uses `queryset.update(status=...)`, which
bypasses `save()` and leaves `published_at` null. It is changed to set both fields
(through `save(update_fields=["status", "published_at"])`) so "published" always
implies an approval timestamp.

**Admin approval**

- The existing `POST /admin-panel/listings/{id}/approve/` sets `published` and
  `published_at`; it remains the approval path.
- `ListingStatusUpdateSerializer` is currently unused dead code. It is removed, and the
  admin action view stays the single status writer.

#### 4.2.4 One-time store backfill

A new idempotent management command:

```bash
python manage.py backfill_listing_stores --dry-run
python manage.py backfill_listing_stores
```

Behaviour:

- Selects listings with `store_id IS NULL`.
- For each, looks up `Store.objects.filter(user=listing.user).first()`.
- If found, sets `listing.store` and saves only that field.
- If not found, counts it as `skipped_no_store` and leaves the row unchanged.
- Prints `scanned`, `linked`, `skipped_no_store`, `skipped_other`.
- `--dry-run` prints the same counts without writing.
- The command is safe to run repeatedly.

Context: `apps/listings/migrations/0009_backfill_listing_stores.py` already performed
this for older deployments and `0010_listing_store_required.py` made the field
non-null. The command covers restored databases, partially migrated environments and
production databases that predate those migrations. On a fully migrated database it
reports `scanned=0`.

#### 4.2.5 Vendor approval

`POST /auth/verification/request/` (service providers):

- `vendor_approval_required=True`: unchanged. The request is stored as `pending`, admins
  are notified, and an admin approves or rejects it.
- `vendor_approval_required=False`:
  - The request is created with `status=approved`, `reviewed_at=now`,
    `reviewed_by=None`, and
    `admin_notes="Auto-approved because vendor approval is disabled."`.
  - `user.is_verified` is set to `True`.
  - If the user has a store, `store.is_verified` is set to `True`. `store.is_published`
    remains the seller's choice.
  - The admin notification is skipped; the normal approval notification is sent.
  - The response remains `201` with the verification request serializer, whose
    `status` field now reads `approved`.

Authentication rule: this does not relax the existing `service_provider`-only rule.

Store onboarding: when `vendor_approval_required=False`, a store **newly created** by
`SellerOnboardingStep1Serializer` is saved with `is_verified=True`, so the flag is
coherent for sellers who never submit a service-provider verification request. Existing
stores are not changed on re-submission.

### 4.3 Money and orders

#### 4.3.1 Delivery fee

New module `apps/commerce/services/delivery.py`:

```python
def calculate_delivery_fee(cart_item, subtotal_ngn) -> Decimal
```

Rules, in order:

1. If `cart_item.listing.listing_type == service`, return `0.00`.
2. If `cart_item.delivery_detail` is `None`, return `0.00`.
3. Load active `ShippingProfile` rows for `cart_item.listing.store`.
4. Match `zone_name` case-insensitively against the address parts in this order:
   `delivery_detail.city`, then `delivery_detail.state`, then
   `delivery_detail.country`. For each part, skip it when blank; otherwise select the
   active profiles whose `zone_name` equals it (case-insensitive), and if at least one
   matches, stop looking at later parts. Ties within a part are broken by lowest
   `flat_rate_cost`, then lowest `id`.
5. If no profile matches, return `0.00`.
6. If `free_shipping_threshold` is not null and `subtotal_ngn >= threshold`, return
   `0.00`.
7. Return `money(flat_rate_cost)`.

The fee is charged once per cart line, not per unit and not per rental day. Amounts are
NGN, matching `ShippingProfile` and the existing conversion convention.

Checkout writes:

- `Order.delivery_fee = fee`
- `Order.total_amount = subtotal + fee`
- commission stays on the goods subtotal only; delivery passes through to the seller in
  full (`accrue_earning` already includes delivery in gross and computes commission from
  the subtotal)
- `CheckoutSession.total_amount` is the sum of the new totals.

#### 4.3.2 Delivery snapshot

Checkout also writes, from the item's `delivery_detail` when present:

- `Order.delivery_address = address, city, state, country` (non-empty parts joined by
  `, `)
- `Order.delivery_contact_name = contact_person`
- `Order.delivery_contact_phone = phone`

This makes the existing invoice delivery block render and gives staff a stable snapshot
even if the saved address later changes.

#### 4.3.3 Invoice

- The financial breakdown becomes:
  - `Subtotal`
  - `Delivery Fee`
  - `Total Amount` (buyer total, i.e. subtotal + delivery)
- The `Escrow Fee:` line is removed.
- A separate, clearly labelled line is added below the total:
  `Sales Commission ({rate}%): {currency} {commission_amount} (deducted from seller proceeds)`.
  It is not part of the buyer total.
- The delivery block renders when `delivery_address` is set.
- A small helper `invoice_summary_rows(order)` returns the label/value pairs so the
  presentation can be unit-tested without parsing PDF bytes.

### 4.4 Status machines

#### 4.4.1 Payout and earnings

- `allocate_payout()` sets each allocated `VendorEarning` to `PROCESSING` when it is
  currently `AVAILABLE` or `PARTIALLY_RELEASED`. This represents funds reserved for an
  in-flight payout.
- `settle_payout()` resolves each allocated earning from
  `AVAILABLE`, `PARTIALLY_RELEASED` or `PROCESSING`:
  - `paid_out_amount >= net_amount` -> `PAID_OUT`
  - otherwise -> `PARTIALLY_RELEASED`
- `fail_payout()` already unwinds `PROCESSING` to `AVAILABLE` or
  `PARTIALLY_RELEASED`; it is kept and covered by tests.
- `release_pending_earnings_task()` is unchanged; it only considers `PENDING` and
  `PARTIALLY_RELEASED`, so reserved earnings are never released twice.

#### 4.4.2 Disputes

- `finalize_refund()` sets disputes on fully refunded orders from `OPEN` or
  `UNDER_REVIEW` to `REFUNDED`, with `resolved_at` and a resolution note that names the
  refund reference. Partial refunds leave the dispute status unchanged.
- New `POST /commerce/disputes/{id}/cancel/`:
  - buyer only;
  - allowed while `OPEN` or `UNDER_REVIEW`;
  - sets `CANCELLED`, `resolved_at=now`, optional `resolution_notes`;
  - returns `200 {"message": "Dispute cancelled successfully."}`.
- `DisputeActionView` gains a `cancel` action for admins; `DisputeResolutionSerializer`
  accepts `resolve`, `refund` and `cancel`, with `resolution_notes` required for
  `resolve`/`refund` and optional for `cancel`.

### 4.5 Notifications

#### 4.5.1 Push subscriptions

New model `PushSubscription`:

| Field | Definition |
|---|---|
| `user` | FK to user, `CASCADE`, `related_name="push_subscriptions"` |
| `endpoint` | `URLField(max_length=500, unique=True)` |
| `p256dh` | `CharField(max_length=200)` |
| `auth` | `CharField(max_length=100)` |
| `user_agent` | `CharField(max_length=300, blank=True)` |
| `is_active` | `BooleanField(default=True, db_index=True)` |
| `created_at` | `auto_now_add` |
| `updated_at` | `auto_now` |

Meta: `db_table = "push_subscriptions"`, `ordering = ["-created_at"]`, index on
`(user, is_active)`.

Endpoints:

- `GET /notifications/push/subscriptions/` - the current user's subscriptions.
- `POST /notifications/push/subscriptions/` - upsert by `endpoint`:
  - body `{"endpoint": "...", "keys": {"p256dh": "...", "auth": "..."}, "user_agent": "..."}`;
  - if the endpoint already belongs to another user, return
    `400 {"error": "This push subscription belongs to another account."}`;
  - returns `201` on create, `200` on update.
- `DELETE /notifications/push/subscriptions/{id}/` - delete the current user's
  subscription; `404 {"error": "Push subscription not found."}` otherwise.
- `GET /notifications/push/public-key/` - `{"public_key": "...", "configured": true}`;
  `configured` is false when `VAPID_PUBLIC_KEY` is empty.

Sending:

- `channels.send_push(delivery)`:
  - no `VAPID_PRIVATE_KEY` -> `skipped`, `"Push is not configured."`;
  - no active subscriptions -> `skipped`, `"No push subscription registered for this user."`;
  - otherwise send to every active subscription with `pywebpush.webpush`, payload
    `{"title": notification.title, "body": notification.message, "url": notification.action_url, "type": event_key}`,
    VAPID claims `{"sub": settings.VAPID_SUBJECT}`;
  - HTTP `404`/`410` deactivates that subscription;
  - at least one success -> `sent`; all failures -> `failed` with the last error;
  - `send_push` catches `WebPushException` and returns `failed` instead of raising, so
    the delivery row records the error and the task does not take its generic retry
    path. Unexpected programming errors still follow the existing task retry behaviour.
- `VAPID_SUBJECT` defaults to `mailto:support@harbourhubglobal.com`.

#### 4.5.2 Notification preferences

- `GET /notifications/preferences/`:
  - creates missing rows for `transactional`, `messages`, `marketing`;
  - returns `[{"category": "...", "in_app": true, "email": true, "sms": false, "push": true}]`.
- `PATCH /notifications/preferences/{category}/`:
  - accepts `in_app`, `email`, `sms`, `push`;
  - `transactional` in-app and email are always on; setting either to `false` returns
    `400 {"error": "Transactional in-app and email notifications cannot be disabled."}`;
  - returns the updated object.
- Staff webhook remains platform-level (`OPS_WEBHOOK_URL`), not a user preference.

#### 4.5.3 SMS

- Termii is the only provider.
- Remove the Twilio branch from `channels.py` and the three Twilio settings.
- Keep the `skipped` result when `SMS_PROVIDER` is empty or the recipient has no phone.
- Document that SMS delivery is verified in staging only (provider credentials and a
  real number are required).

#### 4.5.4 Wording

`apps/notifications/utils.py` changes `"Funds are held in escrow."` to
`"Payment received. Funds are held by Harbour Hub until the order is completed."`

#### 4.5.5 Admin

Register `Notification`, `NotificationPreference`, `NotificationDelivery` and
`PushSubscription` in the Django admin.

### 4.6 Social login

Settings:

- `GOOGLE_CLIENT_ID`
- `APPLE_CLIENT_ID`

Google:

- `verify_google_token` returns a result object with `payload` or `error`.
- Reject when the provider is not configured: `503 {"error": "Google login is not configured."}`.
- Verify `aud == GOOGLE_CLIENT_ID`.
- Verify `iss` is `accounts.google.com` or `https://accounts.google.com`.
- Require `email_verified` to be true (`"true"` or `true`).
- Require an email.

Apple:

- Always verify the signature against Apple's JWKS; the DEBUG bypass is removed.
- Verify `aud == APPLE_CLIENT_ID`, `iss == https://appleid.apple.com`, and expiry.
- Require `email_verified` to be true and an email.
- Unconfigured provider: `503 {"error": "Apple login is not configured."}`.

User creation:

- New social users are created with the verified-email claim, not forced `True`.
- Existing users are not modified.
- `role=BUYER`, unusable password, default `UserPreference` (unchanged).

Contract:

- Both responses declare `access`, `refresh` and `user` (`id`, `email`, `role`).
- Every error string is added to `docs/api/messages.md`.

### 4.7 Admin coverage

Register every model that is currently missing. Audit and log models are read-only.
`User`, `OneTimePassword`, `ReportedContent`, `AdminActionLog`, `Category`,
`UserSearch`, `Inquiry`, `InquiryReply`, `InquiryAttachment`, `Listing`,
`ListingImage`, `ListingDocument`, `ListingView`, `ListingReview`, `StoreReview` and
`Store` are already registered and are left untouched.

| App | Models missing from the admin (to register) |
|---|---|
| `commerce` | `Order`, `OrderItem`, `OrderActivity` (read-only), `CheckoutSession`, `Payment`, `Cart`, `CartItem`, `QuoteRequest`, `RentalExtension`, `WebhookEvent` (read-only), `Refund`, `Dispute` |
| `financials` | `BankAccount`, `VendorEarning`, `Payout`, `VendorWallet`, `WalletTransaction`, `PayoutAllocation` |
| `notifications` | `Notification`, `NotificationPreference`, `NotificationDelivery`, `PushSubscription` |
| `support` | `SupportTicket` |
| `compliance` | `ComplianceDocument` |
| `messaging` | `Conversation`, `Message` |
| `accounts` | `PasswordResetToken` (read-only), `VerificationRequest`, `DeliveryDetail`, `UserPreference`, `UserTwoFactor`, `UserSession` |
| `admin_panel` | `RolePermission`, `AdminProfile`, `PlatformConfig`, `JobListing` |
| `listings` | `SavedItem` |
| `core` | `Feedback` |

Comment-only admin modules are left in place; only the missing registrations above are
added.

Each registration gets a useful `list_display`, `search_fields` and `list_filter` where
the model supports them. Bank account numbers are masked; password/token fields are
never shown in full.

### 4.8 Admin analytics export

`GET /admin-panel/analytics/export/` currently returns two hardcoded rows. It becomes a
real CSV export:

- `date_from` and `date_to` are optional ISO dates; invalid values return
  `400 {"error": "Invalid date format. Use YYYY-MM-DD."}`.
- Metrics, computed in the requested range:
  - total revenue (sum of `Order.total_amount` for `SALES_STATUSES`);
  - paid orders (count of `SALES_STATUSES`);
  - active disputes (`open`, `under_review`);
  - new inquiries;
  - new users;
  - active listings (`published`).
- CSV header `Metric,Value,Period`.
- Permission checks are unchanged.

### 4.9 Smaller correctness fixes

- `EarningsSummarySerializer` becomes
  `total_revenue`, `pending_balance`, `available_balance`, `total_withdrawn`,
  `revenue_change_percent`, `currency`. `total_paid_out` and
  `pending_change_percent` are removed.
- `QuoteRequestActionView` uses explicit messages:
  `Quote cancelled successfully`, `Quote declined successfully`,
  `Quote responded successfully`, `Quote converted successfully`.
- `AdminActionLog.Meta.ordering = ["-created_at"]`, which removes the
  `UnorderedObjectListWarning`.
- Remove the stale `TODO: send email` comment in `PasswordResetRequestSerializer`;
  the view already enqueues the task.
- Remove the placeholder comment in `social_auth.py`.
- Remove the unused `ListingStatusUpdateSerializer`.
- `OrderSerializer` gains read-only `commission_rate` and `commission_amount`.
  `escrow_fee` stays in the response for compatibility but is documented as always
  `0.00` and deprecated.
- The order-fetch convention is already correct: the list serializers expose an integer
  `order_id` and `order_number`; order detail is fetched by integer `id`. A regression
  test pins it; no behaviour change.
- `UserSession.device_type` is populated at login (`mobile`, `tablet`, `desktop`) and the
  serializer derives it from `user_agent` when the stored value is blank, so existing
  sessions display correctly without a data migration.
- `GET /auth/sessions/` stays an unpaginated array and is documented as such.

### 4.10 Routes and webhook path

- Canonical Paystack webhook: `POST /commerce/webhooks/paystack/`.
- Legacy alias: `POST /commerce/payment/webhook/`, marked deprecated in the docs and,
  where drf-spectacular allows it, in the schema.
- Both paths share one view. The schema declares every real response:
  `200 {"status": "ok"}` (plus `{"status": "ok", "detail": "duplicate"}`),
  `400 {"error": "Invalid JSON"}`, `401 {"error": "Invalid signature"}` and
  `500 {"error": "handler failed"}`.
- Canonical analytics: `/analytics/`; legacy `/analytics/analytics/` remains.
- Canonical quotes: `/quotes/sent/`, `/quotes/received/`; legacy
  `/commerce/quotes/sent/`, `/commerce/quotes/received/` remain.
- No client breaks. The generated endpoint reference lists the canonical path first
  and labels the alias deprecated.

### 4.11 Configuration, dependencies, CI and deploy

#### Environment

Add to `.env.example` and `.env.prod.example`:

- `API_DESCRIPTION`
- `OPS_WEBHOOK_URL`
- `SEED_SAMPLE_DATA`
- `SMS_PROVIDER` (`termii`)
- `TERMII_API_KEY`
- `TERMII_SENDER_ID`
- `VAPID_PUBLIC_KEY`
- `VAPID_PRIVATE_KEY`
- `VAPID_SUBJECT`
- `GOOGLE_CLIENT_ID`
- `APPLE_CLIENT_ID`
- `PAYSTACK_WEBHOOK_URL`

Remove:

- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_FROM_NUMBER`

`.env.prod.example` documents the live prefixes with explicit placeholders
(`sk_live_REPLACE_ME`, `pk_live_REPLACE_ME`) so `check_paystack_config` rejects them
until real keys are supplied, and sets
`PAYSTACK_WEBHOOK_URL=https://api.harbourhubglobal.com/commerce/webhooks/paystack/`.

#### Requirements

- `requirements.txt`: production only, every package pinned to the version installed
  and tested. Remove the duplicate `django-debug-toolbar` / `django-extensions`
  entries, move pytest, pytest-django, black, flake8, isort and Faker to dev, add
  `pywebpush`, and bump `reportlab` off 4.1.0. `twilio` is not added.
- `requirements-dev.txt`: `-r requirements.txt` plus pytest, pytest-django,
  pytest-cov, factory-boy, black, flake8, isort, django-debug-toolbar,
  django-extensions and Faker.
- `create_sample_data` remains a development/staging tool; it is removed from
  `build.sh` and its Faker dependency moves to dev.

#### CI

- Python 3.12 (matching `runtime.txt` and the README).
- `python manage.py check`.
- `flake8 apps hb tests --select=F401,F821,F841 --exclude=migrations`.
- `makemigrations --check`, `migrate`, `spectacular --validate`, `pytest -q`.

#### Deploy

- `deploy.yml` uses `secrets.EC2_HOST`, `secrets.EC2_USER` and
  `secrets.EC2_PATH` instead of the hardcoded host and path.
- `build.sh` removes `makemigrations --noinput` and `create_sample_data`; it keeps
  `collectstatic` and `migrate`.
- `runtime.txt` stays `python-3.12.6`.

### 4.12 Documentation and backlog

- Rewrite `docs/figma-backend-gap-checklist.md` as an accurate coverage map with the
  original Figma links; only genuine gaps remain.
- Create `docs/product/future-backlog.md` from `New_Feautures.docx`, then delete the
  binary.
- Update `README.md`: remove the false "Real-time notifications" claim, describe all
  five channels, list the new environment variables, and link the new docs.
- Update `docs/README.md`, `docs/api/README.md`, `docs/api/messages.md`,
  `docs/api/examples.md`, `docs/data-model.md`, `docs/sample-data.md`.
- Regenerate `schema.yml` and `docs/api/endpoints.md`.
- Add `docs/superpowers/plans/2026-11-02-harbour-hub-p5-zero-debt-alignment.md` and
  `docs/superpowers/plans/P5-COMPLETE.md`.

### 4.13 Production Paystack cutover

This is an operational task, not a repository change. It runs only after the new
canonical webhook path is deployed.

Access to the server (read-only until the cutover is confirmed):

```powershell
ssh -v -i "C:\Users\DON COMPUTER\Documents\Works\harbourhub-key.pem" ubuntu@16.16.214.13
```

**Constraint:** Paystack has no public API for reading or setting the webhook URL. Its
Integration API only exposes `payment_session_timeout`; the webhook URL is set in the
Paystack dashboard under **Settings → API Keys & Webhooks**. SSH access therefore cannot
complete the dashboard step (cutover step 5). The dashboard step is performed by the
account owner, or by me only if dashboard access is supplied. The cutover record states
which party did it.

Pre-checks (read-only):

1. Confirm the deployed commit and service health (`systemctl status` for the three
   units, `curl -I https://api.harbourhubglobal.com/api/docs/`).
2. Locate the environment file used by the systemd units.
3. Confirm the current keys start with `sk_test_` / `pk_test_` without printing them
   (length and prefix only).
4. Confirm the new webhook path exists in the deployed code (unsigned `POST` returns
   `401 {"error": "Invalid signature"}`, not `404`).
5. Read the production `PlatformConfig` row (read-only) and record the current
   `enable_buy`, `enable_rent`, `enable_services`, `vendor_approval_required` and
   `listing_approval_required` values, so the behaviour change these flags introduce is
   known before the deploy.

Cutover (after explicit confirmation):

1. Back up the environment file with a timestamp and `600` permissions.
2. Replace `PAYSTACK_SECRET_KEY`, `PAYSTACK_PUBLIC_KEY` and `PAYSTACK_WEBHOOK_URL`
   atomically. Secrets are never echoed to the terminal or written to the repo.
3. Restart `harbourhub-web`, `harbourhub-worker` and `harbourhub-beat`.
4. Run `python manage.py check_paystack_config` with `--send-signed-event`, which:
   - fails if the keys are missing or not `sk_live_` / `pk_live_`;
   - fails if `PAYSTACK_WEBHOOK_URL` is not
     `https://api.harbourhubglobal.com/commerce/webhooks/paystack/`;
   - posts an unsigned request and expects `401`;
   - posts a signed, non-mutating `charge.success` event with a random non-existent
     reference and expects `200`.
5. In the Paystack dashboard, set the **Live Webhook URL** to
   `https://api.harbourhubglobal.com/commerce/webhooks/paystack/` and save. Confirm the
   saved value with the account owner.
6. After the first real live charge, confirm delivery with
   `GET https://api.paystack.co/integration/webhooks/events?status=Delivered` and the
   matching `commerce_orders` / `payments` rows.
7. Verify the app is healthy and that no new test-key signature errors appear.

Rollback:

1. Restore the backed-up environment file.
2. Restart the three services.
3. Restore the previous webhook URL in the Paystack dashboard.
4. Confirm the app is healthy.

New management command:

- `check_paystack_config`: validates the local key prefixes and webhook URL, probes the
  deployed endpoint for `401`, and with `--send-signed-event` sends a signed
  non-mutating event and expects `200`. It never prints a key or a signature.

The live key values are supplied through the server environment or a secure local file.
They are never committed, printed, or stored in the spec.

---

## 5. Data model changes

| Change | Migration |
|---|---|
| New `notifications.PushSubscription` | yes |
| `admin_panel.AdminActionLog.Meta.ordering` | yes (options-only) |
| No change to `Dispute`, `VendorEarning` or `Listing` choices | no |
| No change to `Order` fields | no |
| No change to `ShippingProfile` | no |

No existing rows are deleted. No column is dropped. No table is renamed.

## 6. API surface changes

| Method | Path | Change |
|---|---|---|
| GET | `/platform-config/` | new, public |
| POST | `/listings/` | enabled-type checks; approval rule; store assignment made explicit |
| GET | `/listings/` | disabled types excluded |
| GET | `/listings/{id}/` | disabled types 404 to the public |
| POST | `/listings/{id}/publish/` | approval gate when `listing_approval_required=True` |
| POST | `/auth/verification/request/` | auto-approval when `vendor_approval_required=False` |
| POST | `/commerce/webhooks/paystack/` | new canonical webhook path |
| POST | `/commerce/payment/webhook/` | deprecated alias |
| GET | `/analytics/` | canonical analytics path |
| GET | `/analytics/analytics/...` | deprecated alias |
| GET | `/quotes/sent/`, `/quotes/received/` | canonical |
| GET | `/commerce/quotes/sent/`, `/commerce/quotes/received/` | deprecated aliases |
| GET | `/notifications/preferences/` | new |
| PATCH | `/notifications/preferences/{category}/` | new |
| GET | `/notifications/push/subscriptions/` | new |
| POST | `/notifications/push/subscriptions/` | new |
| DELETE | `/notifications/push/subscriptions/{id}/` | new |
| GET | `/notifications/push/public-key/` | new |
| POST | `/commerce/disputes/{id}/cancel/` | new |
| GET | `/financials/earnings/summary/` | response schema corrected |

## 7. Message changes

| Old | New |
|---|---|
| `Quote declineed successfully` | `Quote declined successfully` |
| `Quote canceled successfully` (from the `f'Quote {action}ed successfully'` template) | `Quote cancelled successfully` |
| `Funds are held in escrow.` | `Payment received. Funds are held by Harbour Hub until the order is completed.` |
| `Escrow Fee:` (PDF label) | removed; `Sales Commission (...)` added below the total |

New messages:

- `Buy listings are currently disabled.`
- `Rent and lease listings are currently disabled.`
- `Service listings are currently disabled.`
- `Listings require admin approval before publishing.`
- `This status can only be set by an administrator.`
- `Dispute cancelled successfully.`
- `This push subscription belongs to another account.`
- `Push subscription not found.`
- `Transactional in-app and email notifications cannot be disabled.`
- `Google login is not configured.`
- `Apple login is not configured.`
- `Invalid date format. Use YYYY-MM-DD.`
- `Verification auto-approved because vendor approval is disabled.` (admin note, not an API message)

The removed Twilio error paths and the old webhook/route aliases are documented as
deprecated rather than deleted from the message catalogue.

## 8. Testing

### 8.1 New and updated tests

- Platform config: public 200, exact keys, values reflect the singleton, no auth.
- Listings:
  - store is always the owner's store; a forged `store` is ignored;
  - no store returns the onboarding error;
  - disabled buy/rent/lease/service create and list behaviour;
  - approval-required create is `draft`;
  - approval-not-required create is `published`;
  - draft cannot self-publish when approval is required;
  - previously approved paused listing can re-publish;
  - a seller cannot set `flagged` or `suspended`;
  - `publish` action is blocked for an unapproved draft and allowed for an admin;
  - Django admin bulk publish fills `published_at`;
  - admin approval publishes.
- Backfill command: dry-run, link, skip, idempotency.
- Vendor approval: auto-approve when false, pending when true.
- Delivery fee: city/state/country match, free threshold, no profile, service, no
  address, tie-break, per-line not per-unit.
- Order delivery snapshot and invoice summary rows.
- Quote messages.
- Order serializer exposes commission fields and keeps `escrow_fee` at `0.00`.
- Order list uses integer `order_id` and keeps `order_number`; detail uses integer id.
- Session list populates `device_type`, including for a blank stored value.
- Earnings summary schema and body.
- Admin analytics export real values and invalid dates.
- AdminActionLog ordering (no warning).
- Payout `PROCESSING` -> `PAID_OUT` / `PARTIALLY_RELEASED`, and failure unwinds.
- Refund sets `Dispute.REFUNDED`; partial refund keeps `UNDER_REVIEW`.
- Dispute cancel endpoint.
- Push subscription CRUD, public key, send success, skipped, 404/410 deactivation.
- Notification preferences defaults and transactional lock.
- Social login: valid, wrong audience, unverified email, invalid signature, missing
  configuration, existing user unchanged.
- Admin registrations present for every model.
- Route aliases resolve to the same views.
- Adopted invoice and quote tests.

### 8.2 Adopted tests

- `apps/commerce/tests.py` -> `tests/test_invoice_pdf.py`, with a real `Store`.
- `apps/commerce/tests_quote.py` -> `tests/test_quote_actions.py`.
- The originals are deleted so pytest has one copy.

### 8.3 Full gate before every commit

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python -m pytest -q
python -m flake8 apps hb tests --select=F401,F821,F841 --exclude=migrations
python manage.py spectacular --file schema.yml --validate
python scripts/generate_api_reference.py
```

The endpoint reference must regenerate with no diff.

## 9. Task breakdown

| # | Task | Commit |
|---|---|---|
| 0 | This spec and the P5 plan | `docs: add the P5 zero-debt design and plan` |
| 1 | Platform config endpoint + listing enabled-type/approval rules + store assignment + backfill command + tests | `feat(listings): enforce platform config and approval rules` |
| 2 | Vendor auto-approval + tests | `feat(accounts): auto-approve vendors when approval is disabled` |
| 3 | Delivery fee, order delivery snapshot, invoice commission, quote messages, earnings schema, analytics export, ordering, wording | `fix(commerce): align fees, invoices and response contracts` |
| 4 | Payout and dispute status machines + cancel endpoint + tests | `feat(commerce): complete payout and dispute status machines` |
| 5 | Push subscriptions, preference endpoints, Termii-only SMS, admin registrations | `feat(notifications): complete push and preference surfaces` |
| 6 | Social login hardening + tests | `feat(accounts): harden Google and Apple login` |
| 7 | Config, requirements, CI, deploy, build, route aliases, schema regeneration | `chore: align configuration, dependencies and routes` |
| 8 | Documentation rewrite, future backlog, P5 completion record, final gate | `docs: record P5 completion and remaining staging checks` |
| 9 | Production Paystack cutover (operational; env swap + signed self-test in code, dashboard webhook URL set by the account owner) | n/a |

Each task runs the full gate before its commit. Task 9 runs only after the code is
deployed and the user confirms the live keys are ready.

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Delivery fees change order totals | Only new orders are affected; existing rows are untouched; tests pin the rule. |
| Sellers use free-text `zone_name` values that do not match addresses | Document the convention; no match means `0.00`, never an error. |
| Approval rules surprise existing sellers | Existing published listings are grandfathered; only new submissions and re-publication are gated. |
| Social login rejects tokens until client IDs are configured | Fail closed with a clear 503; document the two variables. |
| Push needs HTTPS and VAPID keys | `skipped` when unconfigured; `configured` flag on the public-key endpoint. |
| Reportlab bump changes PDF layout | Add the summary-row unit test and an invoice smoke test. |
| Production config flags hide live listings or gate new ones | Read the current `PlatformConfig` before deploy, record the enforced values in the phase record, and note that staff can change them at `/admin-panel/dashboard/config/`. |
| Live Paystack cutover breaks payments | Backup, atomic env rewrite, `check_paystack_config`, signed non-mutating webhook test, documented rollback. |
| Production database is behind the migrations | The backfill command and the normal `migrate` step are idempotent; no data reset. |
| Admin breadth exposes sensitive data | Read-only audit models; masked bank accounts; no token/password fields. |

## 11. Invariants

- Buyers pay no platform fee.
- Commission is seller-side and charged on goods only.
- `Listing.store` is authoritative and always the owner's store.
- `OrderItem.delivery_detail` is the source of the delivery snapshot.
- No existing business data is deleted or rewritten.
- Secrets are never committed, printed, or written to documentation.
- Every new message is added to `docs/api/messages.md`.
- Every API change is regenerated into `schema.yml` and `docs/api/endpoints.md`.

## 12. Open assumptions

1. `ShippingProfile.zone_name` is intended to hold a city, state or country name.
2. `vendor_approval_required=False` also applies to store onboarding, not only the
   verification request, so the flag is coherent for sellers.
3. The live Paystack keys can be supplied through the server environment or a secure
   local file; they are never pasted into the repository.
4. The production services are named `harbourhub-web`, `harbourhub-worker` and
   `harbourhub-beat`, as in `deploy.yml`.
5. Existing published listings remain published when approval is enabled.
6. Paystack's webhook URL is configured in its dashboard, not through an API. The
   account owner performs that step, or supplies dashboard access.
7. The deployed API host is `https://api.harbourhubglobal.com`, matching the requested
   webhook URL.

If any assumption is wrong, the affected section is adjusted before implementation.
