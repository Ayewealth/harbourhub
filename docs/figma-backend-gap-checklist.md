# Figma → backend coverage map (Harbour Hub)

**Figma file:** [Harbour Hub 2025 (Copy)](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-)  
**Backend:** Django REST API under `/api/v1/` ([`hb/api_urls_v1.py`](../hb/api_urls_v1.py))

This page maps each Figma area to the endpoint and model that implements it. It is a **coverage map,
not a promise list**: a row is only marked covered when the contract exists and is documented. Work
that is genuinely not built is collected under [Remaining backlog](#remaining-backlog), and product
features that were deliberately deferred link to [`product/future-backlog.md`](product/future-backlog.md).

| Status | Meaning |
|---|---|
| **Covered** | Model, endpoint, permissions, and status/validation flow exist and are tested. |
| **Partial** | The core flow exists, but a UI detail or a secondary action is not modelled. |
| **Backlog** | No suitable backend support yet; listed under Remaining backlog. |

The exact request/response shapes are in [`api/endpoints.md`](api/endpoints.md), the error strings in
[`api/messages.md`](api/messages.md), worked flows in [`api/examples.md`](api/examples.md), and the
entities and status machines in [`data-model.md`](data-model.md).

---

## 1. Auth

**Figma frames:** [429:3489](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=429-3489), [429:3713](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=429-3713), [429:4017](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=429-4017), [429:3577](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=429-3577), [429:3892](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=429-3892), [429:3621](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=429-3621), [429:3663](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=429-3663)

| Area | Backend contract | Status |
|---|---|---|
| Email/password registration | `POST /auth/register/` — `User`, `UserRegistrationSerializer` | Covered |
| JWT login, refresh, 2FA step-up | `POST /auth/login/`, `POST /auth/refresh/`; `POST /auth/2fa/verify/` when 2FA is enabled | Covered |
| OTP registration / login | `POST /auth/otp/request/`, `POST /auth/otp/verify/`, `POST /auth/set-password/` — `OneTimePassword` | Covered |
| Password change and reset | `POST /auth/password/change/`, `POST /auth/password/reset/request/`, `POST /auth/password/reset/confirm/` — `PasswordResetToken` | Covered |
| Profile read/update | `GET/PATCH /auth/profile/{id}/` — `User`, `UserProfileSerializer` | Covered |
| Two-factor setup | `GET /auth/2fa/status/`, `POST /auth/2fa/setup/`, `GET /auth/2fa/qr/`, `POST /auth/2fa/enable/`, `POST /auth/2fa/disable/` — `UserTwoFactor` | Covered |
| Active sessions | `GET /auth/sessions/`, `DELETE /auth/sessions/{id}/`, `POST /auth/sessions/remove-all/` — `UserSession` | Covered |
| Social login | `POST /auth/social/google/`, `POST /auth/social/apple/` — verified-email OAuth; `503` when the client id is unset | Covered |
| Seller role transition and onboarding | `POST /auth/become-seller/`, `GET /auth/onboarding/status/`, `POST /auth/onboarding/step-1/` (store), `step-2/` (categories), `step-3/` (verification) | Covered |
| Service-provider verification | `POST /auth/verification/request/`, `GET /auth/verification/status/` — `VerificationRequest` | Covered |

Social login is described in [`product/future-backlog.md`](product/future-backlog.md#social-login)
only so it is not re-scoped as missing.

---

## 2. Flow — buy / rent equipment

**Figma frames:** [6007:35289](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=6007-35289), [659:3546](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=659-3546), [2418:33978](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2418-33978), [2418:34684](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2418-34684), [2441:33313](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2441-33313), [2458:34678](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2458-34678), [2485:42349](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2485-42349)

| Area | Backend contract | Status |
|---|---|---|
| Listing detail / browse | `GET /listings/`, `GET /listings/{id}/` — `Listing.listing_type` is `sell`, `rent`, `lease`, or `service` | Covered |
| Add to cart | `POST /commerce/cart/items/`, `GET /commerce/cart/`, `PATCH/DELETE /commerce/cart/items/{item_id}/` — `Cart`, `CartItem` | Covered |
| Rental duration and pricing | `CartItem.duration_days`; `OrderItem` snapshots rental start/end; `POST /commerce/orders/{id}/extend-rental/` and the per-item variant — `RentalExtension` | Covered |
| Payment capture | `POST /commerce/checkout/`, `GET /commerce/payment/verify/{reference}/`, `POST /commerce/webhooks/paystack/` — `CheckoutSession`, `Payment`, `WebhookEvent` | Covered |
| Post-purchase lifecycle | `GET /commerce/orders/{id}/`, `/my-orders/`, `/store-orders/`, `/activity/`, `/ship/`, `/confirm-receipt/`, `/tracking/`, `/cancel/` — `Order`, `OrderItem`, `OrderActivity` | Covered |
| Physical delivery fee | `Order.delivery_fee` resolved at checkout from the seller's active `ShippingProfile` zone; `GET /stores/{slug}/shipping-options/` previews it | Covered |
| Rental availability calendar | No per-date availability model; rentals are duration-based and every published listing is assumed available | Backlog |

---

## 3. Category

**Figma:** [1429:20358](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=1429-20358)

| Area | Backend contract | Status |
|---|---|---|
| Public category list / tree | `GET /categories/`, `GET /categories/{id}/`, `GET /categories/tree/` — `Category` (MPTT) | Covered |
| Admin category CRUD | `GET/POST /categories/admin/`, `GET/PATCH/DELETE /categories/admin/{id}/` — `CategoryAdminViewSet` | Covered |
| Public counts respect disabled listing types | Category serializers count only types whose `PlatformConfig` flag is on | Covered |

---

## 4. Marketplace

**Figma:** [795:18150](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=795-18150)

| Area | Backend contract | Status |
|---|---|---|
| Listing list and filters | `GET /listings/` — `ListingFilter` (price, type, condition, verified, rating, location, date) | Covered |
| Discovery rails | `GET /listings/top-deals/`, `/best-reviewed/`, `/recent-sales/`; `Listing.featured` | Covered |
| Single home-feed composition | No one endpoint returns every rail in one response | Backlog (optional) |

---

## 5. Vendors (public directory)

**Figma:** [795:18185](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=795-18185), [1151:21735](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=1151-21735)

| Area | Backend contract | Status |
|---|---|---|
| Vendor directory | `GET /stores/`, `GET /stores/top/` — `Store` with owner, listing preview, `rating_average`, `review_count`, `sales_count` | Covered |
| Storefront page | `GET /stores/{slug}/` — full profile plus listing preview and counts | Covered |
| Store creation / branding / policies | `POST /stores/`, `PATCH /stores/{slug}/`, `POST /stores/{slug}/publish/`, `/unpublish/` | Covered |

---

## 6. Notifications

**Figma:** [3455:29778](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=3455-29778), [2310:23136](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2310-23136)

| Area | Backend contract | Status |
|---|---|---|
| In-app list, count, read, delete | `GET /notifications/`, `/count/`, `POST /{id}/read/`, `/read-all/`, `DELETE /{id}/`, `/clear/` — `Notification` | Covered |
| Per-category preferences | `GET /notifications/preferences/`, `PATCH /notifications/preferences/{category}/` — `NotificationPreference` | Covered |
| Browser push | `GET /notifications/push/public-key/`, `GET/POST /notifications/push/subscriptions/`, `DELETE /notifications/push/subscriptions/{id}/` — `PushSubscription` | Covered |
| Email / SMS / staff webhook delivery | `NotificationDelivery` rows written by the channel adapters; Termii for SMS, `OPS_WEBHOOK_URL` for staff | Covered |
| Real-time in-app delivery | No WebSocket/SSE; clients poll or rely on web push | Backlog |

---

## 7. Cart

**Figma:** [2100:29135](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2100-29135), [2100:30476](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2100-30476), [2358:12627](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2358-12627), [2310:22749](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2310-22749)

| Area | Backend contract | Status |
|---|---|---|
| Shopping cart | `GET /commerce/cart/`, `POST /commerce/cart/items/`, `PATCH/DELETE /commerce/cart/items/{item_id}/` — `Cart`, `CartItem` | Covered |
| Cart line delivery address | `CartItem.delivery_detail` — `DeliveryDetail` | Covered |
| Quote → cart | `POST /commerce/quotes/{id}/move-to-cart/`, `POST /messages/{id}/messages/{message_id}/move-to-cart/` | Covered |

---

## 8. Search

**Figma:** [2374:32210](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2374-32210), [2374:32292](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2374-32292), [2374:32375](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2374-32375), [2374:32409](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2374-32409)

| Area | Backend contract | Status |
|---|---|---|
| Global search | `GET /search/?q=` — `GlobalSearchView`, returns listings plus stores/categories; uses `ListingListSerializer` | Covered |
| Recent searches | `GET /search/history/` — `UserSearch` | Covered |
| Search suggestions / autocomplete | No suggestions endpoint; the history endpoint is not a prefix service | Backlog (optional) |
| Page feedback | `POST /search/feedback/` — `Feedback` | Covered |

---

## 9. Profile — customer (logged in)

### 9.1 Profile

**Figma:** [2379:29451](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2379-29451), [2475:41246](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2475-41246)

| Area | Backend contract | Status |
|---|---|---|
| View/update profile fields | `GET/PATCH /auth/profile/{id}/` — `full_name`, `company`, `phone`, `location`, `profile_image` | Covered |
| Security extras | Password change/reset, 2FA, and session management exist | Covered |
| Change email with verification | No endpoint; `User.email` is the login identifier and is not editable through the profile serializer | Backlog |

### 9.2 Saved items

**Figma:** [2606:46624](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2606-46624), [2603:45868](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2603-45868)

| Area | Backend contract | Status |
|---|---|---|
| Wishlist / saved listings | `GET /listings/saved/`, `POST /listings/{id}/save/` — `SavedItem` | Covered |

### 9.3 Messages

**Figma:** [2475:39342](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2475-39342), [2490:43942](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2490-43942), [2490:46035](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2490-46035), [2490:46667](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2490-46667)

| Area | Backend contract | Status |
|---|---|---|
| Conversation list and thread | `GET /messages/`, `POST /messages/start/`, `GET /messages/{id}/` — `Conversation`, `Message` | Covered |
| Send and unread counts | `POST /messages/{id}/send/`, `GET /messages/unread/` | Covered |
| Quote actions inside chat | `POST /messages/{id}/request-quote/`, `/request-changes/`, `/messages/{message_id}/move-to-cart/` | Covered |
| Inquiry threads | `GET/POST /inquiries/`, replies under the inquiry viewset — `Inquiry`, `InquiryReply` | Covered |
| Real-time delivery | No WebSocket/SSE; see [`product/future-backlog.md`](product/future-backlog.md#real-time-chat) | Backlog |

### 9.4 Delivery details

**Figma:** [2490:44463](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2490-44463), [2490:47706](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2490-47706), [2490:44715](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2490-44715)

| Area | Backend contract | Status |
|---|---|---|
| Saved addresses | `GET/POST /auth/delivery-details/`, `PATCH/DELETE /auth/delivery-details/{id}/`, `POST /auth/delivery-details/{id}/set-default/` — `DeliveryDetail` | Covered |
| Shipping options for a store | `GET /stores/{slug}/shipping-options/` — active `ShippingProfile` zones | Covered |

### 9.5 Account preferences

**Figma:** [2537:35973](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2537-35973)

| Area | Backend contract | Status |
|---|---|---|
| Locale and interest preferences | `GET/PATCH /auth/preferences/` — `UserPreference` | Covered |
| Notification channel preferences | `GET/PATCH /notifications/preferences/` — `NotificationPreference` | Covered |
| Theme preference | No theme field; presentation-only and can stay client-side | Backlog (optional) |

### 9.6 My store (customer context)

**Figma:** [2549:21962](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2549-21962)

| Area | Backend contract | Status |
|---|---|---|
| Seller dashboard data | `GET /stores/me/`, `/stores/dashboard/metrics/`, `/dashboard/trend/`, `/dashboard/activity/`, `/dashboard/checklist/` | Covered |
| Manage own listings | Listing viewset `my_listings` action plus publish/archive | Covered |

### 9.7 Orders (+ rent detail)

**Figma orders:** [2475:40605](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2475-40605), [2582:39041](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2582-39041), [2583:40490](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2583-40490), [2962:29225](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2962-29225), [2603:43738](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2603-43738), [2603:44062](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2603-44062), [2606:47210](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2606-47210), [2603:45042](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2603-45042), [2603:45284](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2603-45284)  
**Rent detail:** [2971:28405](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2971-28405)

| Area | Backend contract | Status |
|---|---|---|
| Order list | `GET /commerce/orders/`, `/my-orders/`, `/store-orders/` — `Order`; list responses carry `order_number` | Covered |
| Order detail | `GET /commerce/orders/{id}/` — fetch by integer `order_id`/`id` | Covered |
| Status, tracking, activity | `/activity/`, `/tracking/`, `/tracking/update/`, `/ship/`, `/confirm-receipt/` — `OrderActivity` | Covered |
| Invoice download | `GET /commerce/orders/{id}/invoice/pdf/` | Covered |
| Refund / cancellation | `POST /commerce/orders/{id}/cancel/` — `Refund` | Covered |
| Rental extension | `POST /commerce/orders/{id}/extend-rental/`, `/items/{item_id}/extend-rental/` — `RentalExtension` | Covered |
| Disputes | `GET/POST /commerce/disputes/`, `/disputes/{id}/`, `/action/`, `/cancel/` — `Dispute` | Covered |

---

## 10. Profile — vendor (“Become a seller”, My store)

### 10.1 Become a seller onboarding

**Figma:** [2654:39442](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2654-39442), [2655:39678](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2655-39678), [2657:40172](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2657-40172), [2657:40344](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2657-40344), [2660:42360](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2660-42360), [2801:46474](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2801-46474), [2801:46940](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2801-46940), [2805:47942](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2805-47942)

| Area | Backend contract | Status |
|---|---|---|
| Register or promote to seller | `POST /auth/register/` always creates a buyer; `POST /auth/become-seller/` promotes an existing buyer | Covered |
| Three-step onboarding | `POST /auth/onboarding/step-1/` creates the `Store`, `step-2/` sets categories, `step-3/` submits `VerificationRequest`; `GET /auth/onboarding/status/` reports progress | Covered |
| Verification review | Admin `GET /admin-panel/verifications/` and `POST /admin-panel/vendors/{id}/approve/`, `reject/`, or `suspend/` | Covered |
| Automatic approval switch | `PlatformConfig.vendor_approval_required = false` auto-approves the request and the store | Covered |
| Bulk document storage on a seller request | `VerificationRequest.document` accepts one file per request; no multi-document checklist per seller | Partial |

### 10.2 My store (vendor)

**Figma:** [3381:47392](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=3381-47392), [3669:47448](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=3669-47448), [3001:44735](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=3001-44735), [2865:46019](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2865-46019), [2908:57868](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=2908-57868), [3048:28727](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=3048-28727)

| Area | Backend contract | Status |
|---|---|---|
| Manage listings | `GET/POST /listings/`, `PATCH/DELETE /listings/{id}/`, `POST /listings/{id}/publish/`, `/archive/`, `/pause/`, `/resume/` — `Listing` | Covered |
| Store dashboard and analytics | `GET /stores/dashboard/*`, `GET /analytics/` (legacy alias `/analytics/analytics/`), `/analytics/export/` admin | Covered |
| Seller orders | `GET /commerce/orders/store-orders/`, `/recent-sales/` | Covered |
| Earnings, wallet, payouts | `GET /financials/earnings/`, `/earnings/summary/`, `/wallet/`, `/wallet/transactions/`, `/payouts/` — `VendorEarning`, `VendorWallet`, `Payout` | Covered |
| Bank accounts | `GET/POST /financials/bank-accounts/`, `/bank-accounts/{id}/set-default/`, `GET /financials/banks/`, `POST /financials/banks/resolve/` — `BankAccount` | Covered |
| Shipping profiles | `GET/POST /stores/me/shipping/`, `PATCH/DELETE /stores/me/shipping/{id}/` — `ShippingProfile` | Covered |

---

## 11. Admin

**Figma groups:** User auth [4074:60439](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4074-60439), [4074:60784](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4074-60784), [4074:60855](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4074-60855) · Overview [4058:57243](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-57243), [4058:57487](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-57487) · Notifications [4058:57802](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-57802) · Reports [4058:72574](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-72574) · Listings [4058:58668](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-58668) and related frames · Orders [4058:60949](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-60949), [4058:61257](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-61257) · Vendors [4058:62350](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-62350), [4058:62666](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-62666), [4058:62308](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-62308) · Payments [4058:63936](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-63936), [4058:64318](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-64318), [4058:64799](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-64799) · Compliance [4058:66424](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-66424), [4058:66723](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-66723) · Support [4058:67832](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-67832), [4058:68153](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-68153), [4058:68561](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-68561) · Settings [4058:70168](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-70168), [4058:70185](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-70185), [4058:70432](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-70432), [4058:70746](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-70746), [4058:70910](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-70910), [4058:71077](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-71077), [4058:70152](https://www.figma.com/design/VBdPOPc9HFeowWxeA2x0Cf/Harbour-Hub-2025--Copy-?node-id=4058-70152)

| Figma area | Backend contract | Status |
|---|---|---|
| Admin auth and permissions | `POST /auth/login/` plus `IsDashboardStaff` / `HasAdminModulePermission`; `GET /admin-panel/dashboard/me/permissions/`, `/dashboard/matrix/`, `/dashboard/invite/`, `/dashboard/accept-invite/`, `/dashboard/admins/` — `AdminProfile`, `RolePermission` | Covered |
| Overview / KPIs | `GET /analytics/` (alias `/analytics/analytics/`), `GET /admin-panel/payments/stats/`, `/reports/stats/`, `GET /commerce/admin/marketplace-breakdown/` | Covered |
| Notifications | Staff are users and use `GET /notifications/` and the preference/push endpoints; admin-triggered notifications are written through the notification service | Covered |
| Reports / moderation | `GET/PATCH /admin-panel/reports/`, `GET /admin-panel/reports/stats/` — `ReportedContent` | Covered |
| Listings moderation | `GET /admin-panel/listings/`, `POST /admin-panel/listings/{id}/{action}/` — approve, reject, or deactivate | Covered |
| Orders | `GET /admin-panel/orders/`, `GET /admin-panel/orders/{pk_or_num}/tracking/`; refunds through the dispute and order-cancel flows — `Order` | Covered |
| Vendors management | `GET /admin-panel/vendors/`, `POST /admin-panel/vendors/{id}/{action}/`, `GET /admin-panel/users/`, `POST /admin-panel/users/{id}/{action}/`, `GET /admin-panel/verifications/` | Covered |
| Payments | `GET /admin-panel/payments/`, `/payments/stats/`, `POST /admin-panel/payments/payouts/{id}/mark-paid/` — `Payment`, `Payout` | Covered |
| Compliance | `GET/POST /compliance/`, `PATCH /compliance/{id}/`, `POST /compliance/{id}/verify/`, `GET /compliance/summary/` — `ComplianceDocument` | Covered |
| Support | `GET/POST /support/`, `GET/PATCH /support/{id}/`, `POST /support/{id}/resolve/`, `GET /support/summary/`, `POST /support/contact/` — `SupportTicket` | Covered |
| Settings | `GET/PATCH /admin-panel/dashboard/config/` — `PlatformConfig`; public subset at `GET /platform-config/` | Covered |
| Careers | `GET /careers/`; admin `GET/POST/PATCH/DELETE /admin-panel/careers/` — `JobListing` | Covered |
| Audit trail and global search | `GET /admin-panel/activity/`, `GET /admin-panel/search/` — `AdminActionLog` | Covered |
| Conversation monitoring | `GET /admin-panel/conversations/`, `/conversations/{id}/messages/` | Covered |

---

## 12. Engineering hygiene

These items were open at the time the first checklist was written. All are resolved in the current
tree; they stay here so the history is explicit.

| Item | Resolution |
|---|---|
| Global search referenced an undefined `ListingSerializer` | `apps/core/views.py` now imports and uses `ListingListSerializer`. |
| `apps/admin_panel/tasks.py` had broken verification imports | Imports resolve; the module is exercised by the admin notification tests. |
| Analytics URL was registered as `analytics/analytics/...` | Canonical `GET /analytics/` is registered first; `/analytics/analytics/` remains as a deprecated alias. |
| Payments webhook path was only `/commerce/payment/webhook/` | Canonical `POST /commerce/webhooks/paystack/` exists; the old path is a deprecated alias. |
| Quote list paths were only under `/commerce/` | Canonical `GET /quotes/sent/` and `/quotes/received/` exist; the commerce paths remain. |

---

## Remaining backlog

Only items with no implementing contract are listed here. Deferred product features have their own
page.

| Area | Why it is not built | Where it goes |
|---|---|---|
| Advertisements (Google Ads, seller banners, paid placement) | New product surface with campaign models, pricing, approval, and payment | [`product/future-backlog.md#advertisements`](product/future-backlog.md#advertisements) |
| Premium users (subscription, fee discounts, priority placement) | Needs a membership model, billing, and a rule that overrides `Store.commission_rate` | [`product/future-backlog.md#premium-users`](product/future-backlog.md#premium-users) |
| Real-time chat | Needs ASGI/Channels, a Redis channel layer, socket auth, and presence | [`product/future-backlog.md#real-time-chat`](product/future-backlog.md#real-time-chat) |
| Rental availability calendar | Rentals are duration-based; there is no per-date availability or blackout model | Product decision, then a new model and endpoint |
| Change email with verification | `User.email` is the login identifier and is immutable through the profile API | New endpoint plus a token/verification flow |
| One-call home-feed composition | Individual discovery rails exist; no aggregate endpoint | Optional client convenience |
| Search suggestions / autocomplete | Only stored search history exists, not a prefix suggestion service | Optional search enhancement |
| Phone-only authentication | `USERNAME_FIELD` is `email`; phone is a profile field, not a login identifier | Only if Figma explicitly requires phone login |
| Theme preference | Presentation-only; no server field | Client-side setting |

---

*Last updated from the Figma groupings: Auth, buy/rent, category, marketplace, vendors, notifications,
cart, search, customer profile, vendor profile, admin. Every covered row names the endpoint and model
that implement it; anything not built is under Remaining backlog.*
