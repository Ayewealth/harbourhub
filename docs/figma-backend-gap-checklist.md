# Figma → backend gap checklist (Harbour Hub)

**Figma file:** [Harbour Hub 2025 (Copy)](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-)  
**Backend:** Django REST API under `/api/v1/` ([`hb/urls.py`](../hb/urls.py))

**Legend**

| Status | Meaning |
|--------|---------|
| **Done** | Models + endpoints exist and match the flow at a basic level |
| **Partial** | Something exists but does not match the full UI flow (shape, permissions, or persistence) |
| **Missing** | No (or no suitable) backend support yet |

Use the checkboxes under **Backend tasks** as your implementation backlog.

---

## 1. Auth

**Figma frames (examples):** [429:3489](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=429-3489), [429:3713](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=429-3713), [429:4017](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=429-4017), [429:3577](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=429-3577), [429:3892](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=429-3892), [429:3621](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=429-3621), [429:3663](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=429-3663)

| Area | Status | Notes |
|------|--------|--------|
| Email/password registration | **Done** | `POST /api/v1/auth/register/` ([`apps/accounts/urls.py`](../apps/accounts/urls.py)) |
| JWT login + refresh | **Done** | `login/`, `refresh/` |
| OTP register / login | **Done** | `otp/request/`, `otp/verify/` |
| Set password (post-OTP) | **Done** | `set-password/` |
| Password change + reset | **Done** | `password/change/`, `password/reset/*` |
| Profile read | **Done** | `GET …/auth/profile/me/` (router) |

**Backend tasks**

- [ ] Align any **extra fields** in Figma (e.g. marketing consent, referral code) with serializers in [`apps/accounts/serializers.py`](../apps/accounts/serializers.py).
- [ ] If Figma shows **social login (Google/Apple/etc.)**, add OAuth2 flow + user linking (not in repo today).
- [ ] If Figma shows **phone-only auth**, extend OTP/user model beyond current email-centric flow.

---

## 2. Flow — buy / rent equipment

**Figma frames (examples):** [6007:35289](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=6007-35289), [659:3546](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=659-3546), [2418:33978](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2418-33978), [2418:34684](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2418-34684), [2441:33313](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2441-33313), [2458:34678](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2458-34678), [2485:42349](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2485-42349)

| Area | Status | Notes |
|------|--------|--------|
| Listing detail / browse | **Partial** | Listings + filters exist ([`apps/listings/`](../apps/listings/)); rent vs buy is `listing_type` on [`Listing`](../apps/listings/models.py) |
| Add to cart / checkout | **Missing** | No cart, checkout, or order models |
| Rental dates / pricing rules | **Missing** | No rental period, deposits, or availability calendar |
| Payment capture | **Missing** | No payment provider, intents, or webhooks |
| Post-purchase order state | **Missing** | No `Order` / `RentalBooking` lifecycle |

**Backend tasks**

- [ ] Design **Order** (and/or **RentalBooking**) models: buyer, seller, line items → listings, status machine, totals.
- [ ] **Cart** (session or user-scoped): add/update/remove lines, merge on login.
- [ ] **Checkout**: validate inventory/availability, create order draft, attach delivery address.
- [ ] **Payments**: provider integration + webhook idempotency + reconciliation fields on orders.
- [ ] **Rental-specific**: start/end dates, daily/weekly rates, extensions, return flow (if in Figma).

---

## 3. Category

**Figma:** [1429:20358](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=1429-20358)

| Area | Status | Notes |
|------|--------|--------|
| Public category list / tree | **Done** | [`apps/categories/`](../apps/categories/) |
| Admin category CRUD | **Done** | Admin routes under categories |

**Backend tasks**

- [ ] Match any **CMS-style** category extras in Figma (banners, SEO copy) with model fields if needed.

---

## 4. Marketplace

**Figma:** [795:18150](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=795-18150)

| Area | Status | Notes |
|------|--------|--------|
| Listing list + filters | **Done** | [`apps/listings/views.py`](../apps/listings/views.py), [`filters.py`](../apps/listings/filters.py) |
| Featured / home merchandising | **Partial** | `featured` exists on listing; no dedicated “home feed” composition API unless you build one |

**Backend tasks**

- [ ] Optional **home/curated** endpoint (sections: featured, new, by category) if Figma needs it.

---

## 5. Vendors (public directory)

**Figma:** [795:18185](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=795-18185), [1151:21735](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=1151-21735)

| Area | Status | Notes |
|------|--------|--------|
| “Vendor” as user with role `seller` | **Partial** | Users have `role`; no dedicated **VendorProfile** / store slug / policies |
| Vendor storefront page data | **Partial** | Can derive from `User` + `listings` filter by `user_id`; no single “store” resource |
| Vendor metrics (ratings, sales) | **Missing** | No reviews/orders aggregates |

**Backend tasks**

- [ ] **Vendor public profile** model or structured fields: store name, slug, description, banner, policies.
- [ ] `GET /vendors/` and `GET /vendors/{slug}/` (or by user id) returning listings summary + profile.
- [ ] After orders/reviews exist, add **aggregate stats** for vendor cards.

---

## 6. Notifications (in-app)

**Figma:** [3455:29778](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=3455-29778), [2310:23136](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2310-23136)

| Area | Status | Notes |
|------|--------|--------|
| Email notifications | **Partial** | Tasks/emails around inquiries, verification, etc. |
| In-app notification list, read/unread | **Missing** | No `Notification` model + APIs |

**Backend tasks**

- [ ] `Notification` model: user, type, payload JSON, read_at, created_at.
- [ ] `GET /notifications/`, `POST /notifications/{id}/read/`, optional `read_all`.
- [ ] Emit notifications from order/inquiry/payment events (once those domains exist).

---

## 7. Cart

**Figma:** [2100:29135](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2100-29135), [2100:30476](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2100-30476), [2358:12627](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2358-12627), [2310:22749](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2310-22749)

| Area | Status | Notes |
|------|--------|--------|
| Shopping cart | **Missing** | Not implemented |

**Backend tasks**

- [ ] Cart + CartLine models (listing, qty or rental dates, snapshot price).
- [ ] CRUD APIs + merge anonymous → authenticated cart.

---

## 8. Search

**Figma:** [2374:32210](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2374-32210), [2374:32292](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2374-32292), [2374:32375](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2374-32375), [2374:32409](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2374-32409)

| Area | Status | Notes |
|------|--------|--------|
| Global search endpoint | **Partial** | [`GlobalSearchView`](../apps/core/views.py) exists but references undefined `ListingSerializer` (bug) — should use e.g. `ListingListSerializer` |
| Search suggestions / recent | **Missing** | Unless built client-side only |

**Backend tasks**

- [ ] Fix `ListingSerializer` → correct serializer in [`apps/core/views.py`](../apps/core/views.py).
- [ ] Optional: `/search/suggestions?q=` backed by popular queries or prefix index.

---

## 9. Profile — customer (logged in)

### 9.1 Profile

**Figma:** [2379:29451](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2379-29451), [2475:41246](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2475-41246)

| Area | Status | Notes |
|------|--------|--------|
| View/update profile fields | **Done** | [`UserProfileUpdateSerializer`](../apps/accounts/serializers.py) — `full_name`, `company`, `phone`, `location`, `profile_image` |
| Change email / security extras | **Partial** | Password flows exist; email change flow may be missing if Figma shows it |

**Backend tasks**

- [ ] Optional **change email** with verification.
- [ ] Any extra profile fields in Figma → add to `User` or related profile model.

### 9.2 Saved items

**Figma:** [2606:46624](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2606-46624), [2603:45868](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2603-45868)

| Area | Status | Notes |
|------|--------|--------|
| Wishlist / saved listings | **Missing** | No model or endpoints |

**Backend tasks**

- [ ] `SavedListing` (user + listing, unique constraint).
- [ ] `POST/DELETE /saved/{listing_id}/`, `GET /saved/`.

### 9.3 Messages

**Figma:** [2475:39342](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2475-39342), [2490:43942](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2490-43942), [2490:46035](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2490-46035), [2490:46667](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2490-46667)

| Area | Status | Notes |
|------|--------|--------|
| Threaded chat UI | **Partial** | [`apps/inquiries/`](../apps/inquiries/) — inquiry + replies, not full chat threads |
| Realtime delivery | **Missing** | No WebSockets |

**Backend tasks**

- [ ] If Figma is **thread-per-listing**: may be enough to extend inquiry payload (participants, last message, unread counts).
- [ ] If Figma is **generic chat**: add `Conversation` + `Message` models and pagination APIs.
- [ ] Optional: WebSockets or SSE for realtime.

### 9.4 Delivery details

**Figma:** [2490:44463](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2490-44463), [2490:47706](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2490-47706), [2490:44715](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2490-44715)

| Area | Status | Notes |
|------|--------|--------|
| Saved addresses | **Missing** | User has `location` string only |

**Backend tasks**

- [ ] `Address` model (user, line1, city, state, postal, country, default flag).
- [ ] CRUD APIs for checkout and profile.

### 9.5 Account preferences

**Figma:** [2537:35973](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2537-35973)

| Area | Status | Notes |
|------|--------|--------|
| Notification prefs, locale, theme | **Missing** | No `UserPreferences` model |

**Backend tasks**

- [ ] Preferences model + `GET/PATCH /me/preferences/`.

### 9.6 My store (customer context)

**Figma:** [2549:21962](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2549-21962)

| Area | Status | Notes |
|------|--------|--------|
| Seller dashboard data as buyer | **Partial** | If user is seller: `my_listings` exists; “store” branding may need vendor profile (see §5) |

**Backend tasks**

- [ ] Same as vendor **store profile** + listing aggregates.

### 9.7 Orders (+ rent detail)

**Figma (orders):** [2475:40605](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2475-40605), [2582:39041](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2582-39041), [2583:40490](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2583-40490), [2962:29225](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2962-29225), [2603:43738](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2603-43738), [2603:44062](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2603-44062), [2606:47210](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2606-47210), [2603:45042](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2603-45042), [2603:45284](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2603-45284)  
**Rent detail:** [2971:28405](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2971-28405)

| Area | Status | Notes |
|------|--------|--------|
| Order list / detail / statuses | **Missing** | No orders |
| Rental-specific order detail | **Missing** | Tied to booking/rental model |

**Backend tasks**

- [ ] Same as §2 order + rental models and buyer/seller order APIs.

---

## 10. Profile — vendor (“Become a seller”, My store)

### 10.1 Become a seller onboarding

**Figma:** [2654:39442](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2654-39442), [2655:39678](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2655-39678), [2657:40172](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2657-40172), [2657:40344](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2657-40344), [2660:42360](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2660-42360), [2801:46474](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2801-46474), [2801:46940](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2801-46940), [2805:47942](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2805-47942)

| Area | Status | Notes |
|------|--------|--------|
| Register as seller | **Partial** | Registration accepts `role` including `seller` ([`UserRegistrationSerializer`](../apps/accounts/serializers.py)) |
| Buyer → seller after signup | **Missing** | `role` is **read-only** on profile; no `POST /become-seller/` or application workflow |
| KYC / documents for sellers | **Partial** | [`VerificationRequest`](../apps/accounts/models.py) exists but API is oriented to **service_provider** in [`VerificationViewSet`](../apps/accounts/views.py) — align or generalize for sellers |

**Backend tasks**

- [ ] **Seller onboarding application**: optional `SellerApplication` model (status, documents) OR allow controlled `role` transition with audit.
- [ ] Endpoints: submit docs, status polling, admin approval hook (may reuse admin verifications).
- [ ] Unify verification flow for **seller** vs **service_provider** if Figma treats them the same.

### 10.2 My store (vendor)

**Figma:** [3381:47392](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=3381-47392), [3669:47448](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=3669-47448), [3001:44735](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=3001-44735), [2865:46019](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2865-46019), [2908:57868](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2908-57868), [3048:28727](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=3048-28727)

| Area | Status | Notes |
|------|--------|--------|
| Manage listings | **Done** | Listing CRUD + `my_listings`, publish/archive |
| Store analytics in UI | **Partial** | [`apps/analytics/`](../apps/analytics/) is admin-oriented; awkward URL nesting (`analytics/analytics/...`) |
| Seller orders | **Missing** | No orders |

**Backend tasks**

- [ ] Seller-scoped **dashboard** endpoint(s): listing counts, inquiry counts, revenue (after payments).
- [ ] Fix or alias analytics routes for cleaner client usage.
- [ ] Seller order list/detail once orders exist.

---

## 11. Admin

**Figma groups:** User auth [4074:60439](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4074-60439), [4074:60784](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4074-60784), [4074:60855](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4074-60855) · Overview [4058:57243](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-57243), [4058:57487](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-57487) · Notifications [4058:57802](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-57802) · Reports [4058:72574](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-72574) · Listings [4058:58668](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-58668) and related frames · Orders [4058:60949](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-60949), [4058:61257](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-61257) · Vendors [4058:62350](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-62350), [4058:62666](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-62666), [4058:62308](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-62308) · Payments [4058:63936](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-63936), [4058:64318](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-64318), [4058:64799](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-64799) · Compliance [4058:66424](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-66424), [4058:66723](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-66723) · Support [4058:67832](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-67832), [4058:68153](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-68153), [4058:68561](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-68561) · Settings [4058:70168](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-70168), [4058:70185](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-70185), [4058:70432](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-70432), [4058:70746](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-70746), [4058:70910](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-70910), [4058:71077](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-71077), [4058:70152](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-70152)

| Figma area | Status | Notes |
|------------|--------|--------|
| Admin auth | **Partial** | Staff users + JWT; dedicated “admin login” may be same tokens with role checks |
| Overview / KPIs | **Partial** | [`apps/analytics/`](../apps/analytics/) |
| Reports / moderation | **Done** | [`apps/admin_panel/`](../apps/admin_panel/urls.py) — reports, verifications |
| Listings moderation | **Partial** | Listing `status` includes flagged/suspended; confirm admin APIs vs Django admin only |
| Orders | **Missing** | No order domain |
| Vendors management | **Partial** | User list by role may need explicit admin endpoints |
| Payments | **Missing** | No payment admin/refund APIs |
| Compliance | **Missing** | No dedicated compliance module (beyond reports) |
| Support (tickets) | **Missing** | No support ticket models |
| Admin settings | **Missing** | No platform settings API (fees, feature flags) — often env-only today |
| Admin notifications | **Missing** | No in-app admin notification feed |

**Backend tasks**

- [ ] Admin **listing moderation** APIs: list flagged, suspend, restore (if not only via Django admin).
- [ ] Admin **user/vendor** list with filters + actions (verify, suspend).
- [ ] **Orders admin**: list/search/refund hooks after payment integration.
- [ ] **Compliance** artifacts (export logs, KYC document storage policies) as required by product.
- [ ] **Support tickets** (optional): model + assignment + statuses.
- [ ] **Platform settings** model or remote config for admin UI.

---

## 12. Engineering hygiene (not Figma-specific but blocks flows)

- [ ] Fix global search bug: `ListingSerializer` in [`apps/core/views.py`](../apps/core/views.py).
- [ ] Review [`apps/admin_panel/tasks.py`](../apps/admin_panel/tasks.py) for broken imports around verification (if still present).
- [ ] Simplify analytics URL registration in [`apps/analytics/urls.py`](../apps/analytics/urls.py) to avoid duplicated `analytics` path segments.

---

## Suggested build order (backend)

1. **Orders + rental booking** (unlocks buy/rent flow, cart checkout, profile orders, admin orders).  
2. **Payments** (unlocks admin payments + settlement).  
3. **Cart** (can merge with step 1 design-wise).  
4. **Saved items + addresses + preferences** (unlocks large parts of customer profile).  
5. **In-app notifications** (feeds customer + admin notification screens).  
6. **Vendor profile + become-seller** (unifies onboarding with public vendor directory).  
7. **Admin gaps** (vendors CRUD, listing moderation APIs, support, settings).

---

*Last updated from Figma groupings you provided (Auth, buy/rent, category, marketplace, vendors, notifications, cart, search, customer profile, vendor profile, admin).*
