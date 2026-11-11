# Future backlog

This page records the features that are **not** part of the current backend contract. They come from
the former `New_Feautures.docx` request and from the P5 scope decisions. Nothing here is promised by
the API today; each section states what was asked for, what exists in the repository now, and why the
work is deferred.

The rest of the documentation describes only implemented behaviour. If a feature here starts, it
gets its own design spec, plan, and completion record before any endpoint is documented.

---

## Advertisements

**What the document asked for**

- Google Ads alongside the marketplace.
- User advertisements: an "Advertise" button on each product in the store profile.
- The seller enters the advertisement duration, and the cost is calculated automatically from it.
- The seller uploads the banner they want to use, and the banner goes through approval.
- The seller pays after the advertisement is approved.

**Current state**

Nothing is implemented. There is no advertisement or campaign model, no banner upload or moderation
queue, no duration-to-price calculation, no placement/rotation logic, no impression or click
tracking, and no endpoint. There is no `Advertise` action on a listing or store.

**Why it is deferred**

Advertising is a new product surface, not a reconciliation of existing code. It needs models and
migrations (campaign, creative, placement, pricing rule, approval state), a payment path separate from
checkout, an approval workflow in the admin panel, scheduling and rotation, and a measurement story
before the first endpoint can be documented. None of that exists, and inventing it inside the P5
zero-debt work would add new unverified behaviour instead of removing debt. It needs its own phase and
a client-facing contract.

---

## Premium users

**What the document asked for**

- Access to an audition of their products (priority review/placement for listings).
- Direct access to customers.
- A blue-tick verified checkmark.
- Lower transaction and commission fees on completed sales, hires, and rentals.
- Lower ESCROW fees for buyers.

**Current state**

- Verification exists: `User.is_verified` and `Store.is_verified` drive the verified badge, and the
  verification workflow is implemented.
- Commission is already configurable per store through `Store.commission_rate`.
- Buyers pay **no** platform or escrow fee. The `Order.escrow_fee` column remains only for backwards
  compatibility and is always `"0.00"`.
- There is no subscription or membership model, no premium flag, no expiry/renewal, no automatic
  commission override, and no priority-placement or audition mechanism.

The "lower ESCROW fee for buyers" line is obsolete: P5 established that buyers are never charged a
platform fee, so the only fee a premium tier could discount is the seller's sales commission.

**Why it is deferred**

Premium is a pricing and packaging decision before it is a code change. It needs a membership model,
billing and renewal, a rule for how a premium commission rate overrides `Store.commission_rate`
without rewriting historical orders, and a definition of "audition" and "direct access" that the
product team agrees on. Shipping a flag without those decisions would create a second, contradictory
fee rule. The existing per-store commission rate is the supported lever until then.

---

## Social login

**What the document asked for**

The request document did not mention social login; it was part of the earlier scope list.

**Current state**

Implemented and hardened, not deferred:

- `POST /auth/social/google/` accepts an `id_token` or an `access_token`.
- `POST /auth/social/apple/` accepts an `id_token`.
- Both require a verified email address owned by this application's client id.
- `GOOGLE_CLIENT_ID` and `APPLE_CLIENT_ID` configure the providers; an unconfigured provider returns
  `503` with `Google login is not configured.` or `Apple login is not configured.`
- Google is configured in production. Apple is intentionally left unconfigured for now, so
  `/auth/social/apple/` still returns `503` until `APPLE_CLIENT_ID` is supplied.
- Failures return the messages catalogued in [`../api/messages.md`](../api/messages.md#social-login).

This section exists so the feature is not mistakenly re-scoped as missing.

---

## Real-time chat

**What the document asked for**

The request document did not mention real-time chat; it was part of the earlier deferred scope.

**Current state**

HTTP messaging exists: `Conversation` and `Message` models plus the `/messages/` endpoints, and an
inquiry can open a conversation. Notifications are stored in-app and delivered through email, SMS,
web push, and the staff webhook.

There is no WebSocket or ASGI channel layer. The API does not push new messages to an open browser
session; a client learns about them by polling or by a web-push notification.

**Why it is deferred**

Real-time chat needs ASGI deployment, Django Channels (or an equivalent), a Redis channel layer,
token authentication over the socket handshake, presence/typing events, reconnection and message
ordering rules, and a client protocol. That is infrastructure work with its own failure modes, and it
would not reuse the existing synchronous request path. HTTP messaging remains the supported contract
until a dedicated real-time phase lands.
