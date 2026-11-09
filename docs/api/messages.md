# Success and error messages

This catalogue lists the messages the API returns, the HTTP status that carries them, and the
condition that triggers them. It is derived from the view, serializer, service, and webhook code.
When a message is dynamic, the variable part is shown in `{braces}`.

Two response shapes are used:

```json
{"error": "A business-rule failure."}
```

```json
{"field_name": ["A validation failure."]}
```

Success responses usually use `{"message": "..."}`; a few return a domain object or a list in
addition to the message. The generated [endpoint reference](endpoints.md) shows which operations
can return which status codes.

---

## Cross-cutting responses

These come from Django REST Framework or the project's global configuration rather than from a
single view.

| Status | Shape | Message | When |
|---|---|---|---|
| `400` | `{"field": ["..."]}` | Field-specific DRF messages | Missing required field, wrong type, invalid choice, invalid email, password too short, etc. |
| `401` | `{"detail": "..."}` | `Authentication credentials were not provided.` | No `Authorization` header on a protected route. |
| `401` | `{"detail": "...", "code": "..."}` | `Given token not valid for any token type` | Expired, malformed, or blacklisted JWT. |
| `403` | `{"detail": "..."}` | `You do not have permission to perform this action.` | Authenticated but the permission class rejected the request. |
| `404` | `{"detail": "..."}` | `Not found.` | The object does not exist or is outside the user's queryset. |
| `405` | `{"detail": "..."}` | `Method "{method}" not allowed.` | Wrong HTTP verb for the route (for example `PATCH /commerce/cart/items/`). |
| `429` | `{"detail": "..."}` | `Request was throttled. Expected available in ...` | Anonymous/user/burst throttle exceeded. |
| `500` | `{"error": "handler failed"}` | Webhook handler failure | A transient webhook failure; Paystack retries. |
| `502` | `{"error": "..."}` | Gateway failure | Paystack initialization or transfer failed. |
| `503` | `{"status": "unknown", "message": "Gateway unavailable. Try again shortly."}` | Verify poll could not reach Paystack. |

DRF's default field messages are stable and are not repeated per endpoint: `This field is
required.`, `This field may not be blank.`, `Not a valid email address.`, `Ensure this value is
greater than or equal to 0.`, `“{value}” is not a valid choice.`

---

## Authentication and accounts

### Success

| Status | Shape | Message | Endpoint / trigger |
|---|---|---|---|
| `200` | `message` | `OTP sent successfully.` | `POST /auth/otp/request/` |
| `200` | `message` | `OTP verified successfully. Proceed to complete registration.` | `POST /auth/otp/verify/` with `purpose=registration` |
| `200` | `message` | `OTP verified successfully. Login complete.` | `POST /auth/otp/verify/` with `purpose=login` |
| `200` | `message` | `Password has been set successfully.` | `POST /auth/set-password/` |
| `200` | `message` | `Password changed successfully` | `POST /auth/password/change/` |
| `200` | `message` | `Password reset successfully` | `POST /auth/password/reset/confirm/` |
| `200` | `message` | `If an account with this email exists, a password reset email has been sent.` | `POST /auth/password/reset/request/` (does not reveal whether the email exists) |
| `201` | `message` | `Verification request submitted successfully` | `POST /auth/verification/request/`; status is `approved` automatically when `vendor_approval_required` is off |
| `200` | `message` | `Default delivery address updated.` | `POST /auth/delivery-details/{id}/set-default/` |
| `200` | `message` | `2FA enabled successfully.` | `POST /auth/2fa/enable/` |
| `200` | `message` | `2FA disabled successfully.` | `POST /auth/2fa/disable/` |
| `200` | `message` | `2FA verified successfully.` | `POST /auth/2fa/verify/` |
| `200` | `message` | `Please complete 2FA verification.` | `POST /auth/login/` when 2FA is enabled (returns `requires_2fa` and a signed token) |
| `200` | `message` | `Session removed successfully.` | `DELETE /auth/sessions/{id}/` |
| `200` | `message` | `All other sessions removed.` | `DELETE /auth/sessions/remove-all/` |
| `200` | `message` | `Account upgraded to seller.` | `POST /auth/become-seller/` |
| `200` | `message` | `Business details saved.` | `POST /auth/onboarding/step-1/` |
| `200` | `message` | `Categories saved.` | `POST /auth/onboarding/step-2/` |
| `200` | `message` | `Verification submitted. Your store setup request has been received. We will activate your store once verification is complete.` | `POST /auth/onboarding/step-3/` |

### Errors

| Status | Shape | Message | Trigger |
|---|---|---|---|
| `403` | `error` | `User account is inactive.` | Login with a suspended account. |
| `404` | `error` | `No account found for this email.` | OTP login for an unknown email. |
| `404` | `error` | `Session not found.` | Removing a session that is not the caller's. |
| `400` | `error` | `Only service providers can request verification` | Legacy verification request by another role. |
| `400` | `error` | `User is already verified` | Verification request for an approved account. |
| `400` | `error` | `Only service providers can check verification status` | Legacy status check by another role. |
| `400` | `error` | `You are already a seller.` | `POST /auth/become-seller/` twice. |
| `400` | `error` | `Please complete step 1 first.` | Onboarding step 2 before step 1. |
| `400` | `error` | `Please complete steps 1 and 2 first.` | Onboarding step 3 before steps 1–2. |
| `400` | `validation` | `Registration always creates a buyer account. Use seller onboarding.` | Registration with `role` other than `buyer`. |
| `400` | `validation[email]` | `No active account found with this email address.` | Login with an unknown or inactive email. |
| `400` | `validation` | `Invalid OTP code.` | Wrong OTP. |
| `400` | `validation` | `OTP has expired or already used.` | OTP outside its window or reused. |
| `400` | `validation[password]` | `Password is required if you haven't verified via OTP.` | Registration without a password and without a used registration OTP. |
| `400` | `validation[password_confirm]` | `Password confirmation doesn't match.` | Password mismatch. |
| `400` | `validation` | `Old password is incorrect.` | Password change with the wrong current password. |
| `400` | `validation[new_password_confirm]` | `New password confirmation doesn't match.` | Password change mismatch. |
| `400` | `validation` | `Token has expired or been used.` | Password-reset token reuse/expiry. |
| `400` | `validation` | `Invalid token.` | Malformed password-reset token. |
| `400` | `validation` | `Invalid code.` | 2FA setup/verify with a wrong TOTP. |
| `400` | `validation` | `2FA not set up. Please request setup first.` | Enabling 2FA before setup. |
| `400` | `validation` | `2FA is not enabled.` | Disabling 2FA when it is off. |
| `400` | `validation` | `2FA session expired. Please log in again.` | Expired signed 2FA login token. |
| `400` | `validation` | `Invalid 2FA session token.` | Malformed 2FA login token. |
| `400` | `validation` | `Invalid user or 2FA not enabled.` | 2FA verify for a user without 2FA. |
| `400` | `validation` | `Invalid 2FA code.` | 2FA login code mismatch. |
| `400` | `validation` | `You do not have permission to assign that role.` | Staff role change beyond the caller's authority. |
| `400` | `validation` | `You cannot modify a super admin.` | Editing a super admin without authority. |
| `400` | `validation` | `Only super admins can assign admin roles.` | Non-super-admin assigning an admin role. |
| `400` | `validation` | `Unknown business type.` | Onboarding with an unsupported business type. |
| `400` | `validation` | `No valid categories found.` | Onboarding step 2 with no valid category ids. |
| `400` | `validation` | `You must confirm documents are valid.` | Onboarding step 3 without confirmation. |
| `400` | `validation` | `Document must be 5 MB or smaller.` | Oversized verification document. |

### Social login

| Status | Shape | Message |
|---|---|---|
| `400` | `error` | `Either id_token or access_token is required.` |
| `400` | `error` | `Invalid Google token.` |
| `400` | `error` | `Google email address is not verified.` |
| `400` | `error` | `Google token does not contain an email address.` |
| `400` | `error` | `Could not verify the Google token.` |
| `400` | `error` | `id_token is required.` |
| `400` | `error` | `Invalid Apple token.` |
| `400` | `error` | `Apple email address is not verified.` |
| `400` | `error` | `Apple token does not contain an email address.` |
| `503` | `error` | `Google login is not configured.` |
| `503` | `error` | `Apple login is not configured.` |

---

## Listings and saved items

### Success

| Status | Shape | Message | Endpoint |
|---|---|---|---|
| `200` | `message` | `Listing published successfully` | `POST /listings/{id}/publish/` |
| `200` | `message` | `Listing archived successfully` | `POST /listings/{id}/archive/` |
| `200` | `message` | `Listing paused successfully` | `POST /listings/{id}/pause/` |
| `200` | `message` | `Listing resumed successfully` | `POST /listings/{id}/resume/` |
| `200` | `message` | `{n} image(s) uploaded successfully` | `POST /listings/{id}/images/` |
| `200` | `message` | `Image {image_id} set as primary successfully` | `POST /listings/{id}/images/{image_id}/primary/` |
| `200` | `message` | `Image deleted successfully.` | `DELETE /listings/{id}/images/{image_id}/` |
| `200` | `message` | `Listing already saved` | `POST /listings/{id}/save/` when already saved |
| `201` | `message` | `Listing saved successfully` | `POST /listings/{id}/save/` |
| `200` | `message` | `Listing removed from saved items` | `DELETE /listings/{id}/save/` |

### Errors

| Status | Shape | Message | Trigger |
|---|---|---|---|
| `400` | `error` | `Cannot delete listing. There are active orders associated with it.` | Delete with a paid/active order item. |
| `400` | `error` | `Cannot delete listing. There are pending quote requests.` | Delete with pending quotes. |
| `400` | `error` | `Buy listings are currently disabled.` | Create/publish a `sell` listing while `enable_buy` is off; also returned by the public list. |
| `400` | `error` | `Rent and lease listings are currently disabled.` | Create/publish a `rent`/`lease` listing while `enable_rent` is off. |
| `400` | `error` | `Service listings are currently disabled.` | Create/publish a `service` listing while `enable_services` is off. |
| `400` | `error` | `Listings require admin approval before publishing.` | Publish/set `published` while `listing_approval_required` is on and the listing has not been approved. |
| `400` | `error` | `Only draft listings can be published` | Publish from a non-draft status. |
| `400` | `error` | `Listing cannot be published until its store is active.` | Publish with an inactive store. |
| `400` | `error` | `Only published listings can be paused` | Pause from a non-published status. |
| `400` | `error` | `Only paused listings can be resumed` | Resume from a non-paused status. |
| `400` | `error` | `No images provided` | Image upload with an empty payload. |
| `400` | `error` | `A listing can have a maximum of {max} images. You currently have {current}, trying to add {adding}.` | Image cap exceeded. |
| `400` | `error` | `image_id is required` | Set-primary without `image_id`. |
| `400` | `error` | `You cannot save your own listing` | Saving a listing you own. |
| `400` | `error` | `{filename} exceeds the {limit}MB limit.` | Upload over the configured image size. |
| `400` | `error` | `{filename} is not an allowed image type (JPEG, PNG, WebP only).` | Unsupported image MIME type. |
| `401` | `detail` | `Authentication required.` | Listing create without a token. |
| `403` | `error` | `Permission denied` | Acting on a listing you do not own. |
| `404` | `error` | `Image not found for this listing` | Image id does not belong to the listing. |
| `404` | `error` | `Listing was not in your saved items` | Unsave when not saved. |

### Serializer validation

| Status | Shape | Message |
|---|---|---|
| `400` | `validation` | `Image file too large (> 10MB)` |
| `400` | `validation` | `Unsupported image type. Only JPEG, PNG, and WebP are allowed.` |
| `400` | `validation` | `Document file too large (> 50MB)` |
| `400` | `validation` | `Unsupported file type. Only PDF, DOC, DOCX, XLS, XLSX, TXT, and images are allowed.` |
| `400` | `validation` | `Selected category is not active.` |
| `400` | `validation` | `Only service providers can create service listings.` |
| `400` | `validation` | `Only sellers can create equipment listings.` |
| `400` | `validation` | `Price cannot be negative.` |
| `400` | `validation` | `You can only change featured flag for your own listings.` |
| `400` | `validation[detail]` | `Authentication is required to create a listing.` |
| `400` | `validation[store]` | `Complete seller onboarding before creating a listing.` |

---

## Stores and categories

| Status | Shape | Message | Trigger |
|---|---|---|---|
| `200` | `message` | `Store published successfully` | Publish an unpublished store. |
| `200` | `message` | `Store unpublished successfully` | Unpublish a published store. |
| `400` | `error` | `Store is already published` | Publish twice. |
| `400` | `error` | `Store is already unpublished` | Unpublish twice. |
| `400` | `validation` | `Category cannot be its own parent.` | Category tree cycle. |
| `400` | `validation` | `Category with this name already exists.` | Duplicate category name. |
| `400` | `validation` | `This would create a circular reference.` | Moving a category under its descendant. |

---

## Cart, checkout, payments, orders, and rentals

### Success

| Status | Shape | Message | Endpoint |
|---|---|---|---|
| `200` | `message` | `Cart cleared.` | `DELETE /commerce/cart/` |
| `200` | `message` | `Item removed from cart.` | `PATCH /commerce/cart/items/{id}/` with `quantity <= 0`, or `DELETE` the item |
| `201` | `message` | `{n} order(s) created.` | `POST /commerce/checkout/` |
| `200` | `message` | `Payment confirmed.` | `GET /commerce/payment/verify/{reference}/` when the payment is already `success` |
| `200` | `message` | `Payment was not completed.` | Verify when the payment is `failed`/`refunded` |
| `200` | `message` | `Awaiting webhook confirmation.` | Verify when Paystack says success but the local payment is still `pending` |
| `200` | `message` | `Payment not completed.` | Verify when Paystack says the charge did not complete |
| `503` | `message` | `Gateway unavailable. Try again shortly.` | Verify when Paystack is unreachable |
| `200` | `message` | `Order marked as shipped` | `POST /commerce/orders/{id}/ship/` |
| `200` | `message` | `Receipt confirmed` | `POST /commerce/orders/{id}/confirm-receipt/` |
| `200` | `message` | `Order cancelled successfully` | Cancel an unpaid order |
| `202` | `message` | `Refund requested. The order will be cancelled once the gateway confirms.` | Cancel a paid order; response also contains `refund_id` and `refund_status` |
| `201` | `message` | `Complete payment to extend the rental.` | `POST /commerce/orders/{id}/items/{item_id}/extend-rental/`; response contains the payment/authorization URL |
| `200` | `message` | `Quote cancelled successfully` | `POST /commerce/quotes/{id}/cancel/` |
| `200` | `message` | `Quote declined successfully` | `POST /commerce/quotes/{id}/decline/` |
| `200` | `message` | `Quote responded successfully` | `POST /commerce/quotes/{id}/respond/` |
| `200` | `message` | `Quote converted successfully` | `POST /commerce/quotes/{id}/convert/` |
| `200` | `message` | `Quote moved to cart successfully.` | `POST /commerce/quotes/{id}/move-to-cart/` and the messaging equivalent |
| `400` | `message` | `Payment already successful` | `POST /commerce/checkout/session/{id}/retry/` on a paid session |
| `200` | `message` | `Dispute resolved. Funds released to vendor escrow.` | `POST /commerce/disputes/{id}/action/` with `action=resolve` (admin). |
| `200` | `message` | `Refund requested. The dispute closes when the gateway confirms.` | `POST /commerce/disputes/{id}/action/` with `action=refund` (admin). |
| `200` | `message` | `Dispute cancelled successfully.` | `POST /commerce/disputes/{id}/cancel/` by the buyer, or an admin `cancel` action. |

`POST /commerce/disputes/` returns the created `Dispute` object with `201`, not a `message`.
Checkout takes no delivery address: each cart item carries its own `delivery_detail`.

### Errors

| Status | Shape | Message | Trigger |
|---|---|---|---|
| `403` | `error` | `Permission denied` | Order action by a user who is neither buyer nor seller. |
| `400` | `error` | `Order cannot be cancelled at this stage` | Cancel a fulfilled/cancelled order. |
| `400` | `error` | `No successful payment found for this order` | Paid-cancel without a successful payment row. |
| `400` | `error` | `Order has no item.` | Legacy extend-rental on an order without an item. |
| `400` | `error` | `Rentals are extended per item and require payment. Use the item endpoint.` | Legacy `POST /commerce/orders/{id}/extend-rental/`; the response also contains `item_id` and `endpoint`. |
| `400` | `error` | `This order cannot be extended yet.` | Extension before the order is paid/confirmed/active. |
| `400` | `error` | `This item has no rental end date.` | Extension for a buy item. |
| `400` | `error` | `duration_days must be an integer` | Non-integer extension length. |
| `400` | `error` | `duration_days must be positive` | Zero/negative extension length. |
| `400` | `error` | `duration_days or new_end_date is required` | Extension without a length or date. |
| `400` | `error` | `Invalid date format. Use YYYY-MM-DD` | Unparseable `new_end_date`. |
| `400` | `error` | `New end date must be after the current end date` | Extension does not move the date forward. |
| `400` | `error` | `The new end date must be in the future` | Extension date in the past. |
| `400` | `error` | `carrier and tracking_id are required` | Ship without both fields. |
| `400` | `error` | `These listings have no store and cannot be checked out: {listing titles}.` | Checkout with a storeless listing. |
| `400` | `error` | `Payment gateway unavailable.` | Rental-extension payment initialization failed. |
| `400` | `error` | `Failed to re-initialize payment gateway.` | Retry initialization failed. |
| `400` | `error` | `No payment is linked to this order.` | Invoice/refund action without a payment. |
| `400` | `error` | `Invalid seller-triggered tracking event. Allowed events are: {events}` | Tracking update with an event the seller may not fire. |
| `400` | `error` | `Invalid action` (quotes) or `Invalid action.` (disputes) | Unknown quote or dispute action. |
| `400` | `error` | `Only buyer can cancel` | Quote cancel by the seller. |
| `400` | `error` | `Only pending quotes can be cancelled` | Cancel a responded/converted quote. |
| `400` | `error` | `Only buyer can decline` | Quote decline by the seller. |
| `400` | `error` | `Cannot decline this quote` | Decline a non-pending quote. |
| `400` | `error` | `Only listing owner can respond` | Quote response by the buyer. |
| `400` | `error` | `Only pending quotes can be responded to` | Respond twice. |
| `400` | `error` | `Only responded quotes can be converted` | Convert a non-responded quote. |
| `502` | `error` | `Payment gateway unavailable. Your cart is intact.` | Checkout initialization failed; response also contains `payment_id` and `retry_url`. |
| `400` | `error` | `Cannot '{event}' an order in status '{status}'.` | Invalid lifecycle transition (`InvalidTransition`). |
| `400` | `error` | `Unknown event '{event}'.` | Unknown lifecycle event. |
| `400` | `error` | `Refund amount must be greater than zero.` | Refund of zero. |
| `400` | `error` | `Refund amount exceeds payment amount.` | Refund larger than the payment. |
| `400` | `error` | `Only successful payments can be refunded.` | Refund of a pending/failed payment. |
| `400` | `error` | `The payment gateway rejected the refund request.` | Paystack rejected the refund. |

### Serializer validation

| Status | Shape | Message |
|---|---|---|
| `400` | `validation` | `Listing must be published.` |
| `400` | `validation` | `Quote does not belong to you.` |
| `400` | `validation` | `This listing is not available.` |
| `400` | `validation` | `duration_days is required for rent/lease.` |
| `400` | `validation` | `Delivery address not found.` (under `delivery_detail`) | Another user's `delivery_detail` on `POST /commerce/cart/items/`. |
| `400` | `validation` | `You must accept the terms and conditions.` |
| `400` | `validation` | `At least one cart item is required.` |
| `400` | `validation` | `No valid cart items found.` |
| `400` | `validation` | `Cart is empty.` |

### Webhook

| Status | Shape | Message | Trigger |
|---|---|---|---|
| `401` | `error` | `Invalid signature` | Missing/wrong `x-paystack-signature`. |
| `400` | `error` | `Invalid JSON` | Body is not valid JSON. |
| `500` | `error` | `handler failed` | Transient handler failure; Paystack retries. |
| `200` | `status` | `{"status": "ok"}` | Event accepted, whether it was processed or marked `ignored` (unknown event type). |
| `200` | `status` + `detail` | `{"status": "ok", "detail": "duplicate"}` | The same `(provider, event_type, gateway_event_id)` was already recorded; no side effects. |

---

## Reviews

| Status | Shape | Message | Trigger |
|---|---|---|---|
| `400` | `validation` | `You can only review published listings.` | Review a draft/paused listing. |
| `400` | `validation` | `You can only review active, published stores.` | Review an inactive store. |
| `400` | `validation` | `You cannot review your own listing.` | Self-review. |
| `400` | `validation` | `You can only review a listing you have purchased.` | No paid order for the listing. |
| `400` | `validation` | `You have already reviewed this listing.` | Duplicate listing review. |
| `400` | `validation` | `You cannot review your own store.` | Self-review of a store. |
| `400` | `validation` | `You can only review a store you have purchased from.` | No paid order from the store. |
| `400` | `validation` | `You have already reviewed this store.` | Duplicate store review. |

---

## Inquiries and messaging

### Inquiries

| Status | Shape | Message | Trigger |
|---|---|---|---|
| `201` | `message` | `Reply sent successfully` | `POST /inquiries/{id}/reply/` |
| `200` | `message` | `Inquiry marked as spam` | `POST /inquiries/{id}/mark_spam/` |
| `200` | `message` | `Inquiry closed` | `POST /inquiries/{id}/close/` |
| `403` | `error` | `Only inquiry recipient can reply` | Reply by the sender. |
| `403` | `error` | `Only inquiry recipient can mark as spam` | Spam action by the sender. |
| `403` | `error` | `Permission denied` | Close by a non-participant. |
| `400` | `validation` | `Attachment too large (max 25MB).` | Oversized attachment. |
| `400` | `validation` | `Unsupported attachment type.` | Unsupported attachment MIME. |
| `400` | `validation` | `Inquiry context missing.` | Reply without an inquiry context. |
| `400` | `validation` | `Only the listing owner may reply to this inquiry.` | Serializer-level reply guard. |
| `400` | `validation` | `Listing must be provided.` | Inquiry without a listing. |
| `400` | `validation` | `Cannot send inquiry for an unpublished listing.` | Inquiry on a non-published listing. |
| `400` | `validation` | `You cannot send an inquiry to your own listing.` | Self-inquiry. |

### Messaging

| Status | Shape | Message | Trigger |
|---|---|---|---|
| `200` | `message` | `Quote moved to cart successfully.` | `POST /messages/.../move-quote-to-cart/` |
| `403` | `error` | `Permission denied` | Conversation access by a non-participant. |
| `400` | `error` | `This conversation has no listing attached.` | Listing action on a listing-less conversation. |
| `400` | `error` | `No quote attached to this message.` | Move-to-cart without a quote. |
| `400` | `error` | `Quote must be in responded status to move to cart.` | Move a non-responded quote. |
| `400` | `validation` | `Message body is required for text messages.` | Text message without a body. |
| `400` | `validation` | `You cannot start a conversation with yourself.` | Self-conversation. |
| `400` | `validation` | `Vendor not found.` | Unknown vendor id. |
| `400` | `validation` | `Listing not found.` | Unknown listing id. |

---

## Notifications

| Status | Shape | Message | Trigger |
|---|---|---|---|
| `200` | `message` | `Notification marked as read.` | `POST /notifications/{id}/read/` |
| `204` | `message` | `Notification deleted.` | `DELETE /notifications/{id}/` |
| `200` | `message` | `{n} notification(s) marked as read.` | `POST /notifications/read-all/` |
| `204` | `message` | `{n} notification(s) deleted.` | `DELETE /notifications/clear/` |
| `404` | `error` | `Notification not found.` | Another user's notification, or an unknown id. |
| `404` | `error` | `Unknown notification category.` | Preference update for a category outside `transactional`, `messages`, `marketing`. |
| `400` | `error` | `Transactional in-app and email notifications cannot be disabled.` | Preference update turning off `in_app` or `email` for `transactional`. |
| `400` | `error` | `endpoint, keys.p256dh and keys.auth are required.` | Push subscription without the required browser keys. |
| `400` | `error` | `This push subscription belongs to another account.` | Registering an endpoint owned by another user. |
| `404` | `error` | `Push subscription not found.` | Deleting a subscription that is not the caller's. |

---

## Financials and payouts

| Status | Shape | Message | Trigger |
|---|---|---|---|
| `200` | `message` | `Default bank account updated.` | `POST /financials/bank-accounts/{id}/set-default/` |
| `400` | `error` | `Could not resolve account` | Paystack account-name resolution failed. |
| `400` | `error` | `account_number and bank_code are required` | Resolve without both fields. |
| `200` | `message` | `Payout frozen successfully.` | Admin freeze. |
| `200` | `message` | `Payout unfrozen successfully.` | Admin unfreeze. |
| `400` | `error` | `Payout is already frozen.` | Freeze twice. |
| `400` | `error` | `Cannot freeze a {status} payout.` | Freeze a paid/failed payout. |
| `400` | `error` | `Payout is not frozen.` | Unfreeze a non-frozen payout. |
| `400` | `validation` | `Account number must contain only digits.` | Non-numeric account number. |
| `400` | `validation` | `Account number must be 10 digits.` | Wrong length. |
| `400` | `validation` | `Bank account does not belong to you.` | Payout to another user's bank account. |
| `400` | `validation` | `Amount must be greater than zero.` | Zero/negative payout. |
| `400` | `validation` | `Wallet not found.` | User without a store wallet. |
| `400` | `validation[store]` | `No store is associated with this account.` | Payout without a store. |
| `400` | `validation` | `Insufficient balance. Available: {available}` | Payout amount above the wallet balance (serializer guard). |
| `400` | `validation[amount]` | `Insufficient available balance.` | Balance changed between validation and creation (race guard). |

---

## Admin panel

| Status | Shape | Message | Trigger |
|---|---|---|---|
| `200` | `message` | `Content report resolved successfully` | Resolve a report. |
| `200` | `message` | `Content report dismissed successfully` | Dismiss a report. |
| `200` | `message` | `Verification approved successfully.` | Approve a verification. |
| `200` | `message` | `Verification rejected successfully.` | Reject a verification. |
| `200` | `message` | `Vendor approved successfully.` | Approve a vendor. |
| `200` | `message` | `Vendor rejected.` | Reject a vendor. |
| `200` | `message` | `Vendor suspended.` | Suspend a vendor. |
| `200` | `message` | `Listing approved successfully.` | Approve a listing. |
| `200` | `message` | `Listing rejected.` | Reject a listing. |
| `200` | `message` | `Listing deactivated.` | Deactivate a listing. |
| `200` | `message` | `Payout marked as paid.` | Mark a payout settled. |
| `200` | `message` | `User suspended successfully.` | Suspend a user. |
| `200` | `message` | `User resumed successfully.` | Resume a user. |
| `200` | `message` | `Admin updated successfully.` | Update an admin. |
| `200` | `message` | `Admin {name} removed.` | Remove an admin. |
| `200` | `message` | `Access revoked for {name}` | Revoke dashboard access. |
| `200` | `message` | `Account activated. You can now log in as {email}` | Activate an invited admin. |
| `400` | `error` | `Invalid action.` | Unknown admin action. |
| `400` | `error` | `Only pending requests can be approved.` | Approve a non-pending request. |
| `400` | `error` | `Only pending requests can be rejected.` | Reject a non-pending request. |
| `400` | `error` | `Payout already marked as paid.` | Settle twice. |
| `400` | `error` | `Payout has no allocations and cannot be settled.` | Settle an empty payout. |
| `400` | `error` | `Invalid date format. Use YYYY-MM-DD.` | Bad analytics date filter. |
| `400` | `error` | `User is not a dashboard admin` | Dashboard action on a non-admin. |
| `400` | `error` | `User is not an admin` | Admin action on a non-admin. |
| `403` | `error` | `Permission denied. Super Admin role required for platform configuration.` | Non-super-admin platform config. |
| `403` | `error` | `Cannot suspend or resume admin users.` | Suspend/resume an admin. |
| `404` | `error` | `User not found` | Unknown user id. |
| `400` | `validation` | `Invalid or expired invite token.` | Expired admin invite. |
| `400` | `validation` | `Each module needs 'view' and 'manage' booleans` | Malformed role matrix. |
| `400` | `validation` | `Invalid content type.` | Report with an unknown content type. |
| `400` | `validation` | `Invalid content type mapping.` | Report type not mapped to a model. |
| `400` | `validation` | `Reported content does not exist.` | Report a missing object. |
| `400` | `validation` | `Authentication required.` | Report without a user. |
| `400` | `validation` | `You have already reported this content.` | Duplicate report. |

---

## Compliance, support, and search

| Status | Shape | Message | Trigger |
|---|---|---|---|
| `200` | `message` | `Document {status}.` | Compliance document status change. |
| `200` | `message` | `Ticket marked as resolved.` | Resolve a support ticket. |
| `400` | `error` | `Ticket is already resolved.` | Resolve twice. |
| `201` | `message` | `Message sent successfully.` | Add a ticket message. |
| `200` | `message` | `Search history cleared` | Clear search history. |
| `400` | `error` | `Search query must be at least 2 characters.` | Too-short search. |
| `400` | `error` | `topic field is required.` | Feedback without a topic. |
| `400` | `error` | `feedback field is required.` | Feedback without a value. |
| `400` | `error` | `Invalid feedback value. Must be 'helpful' or 'not_helpful'.` | Unknown feedback value. |
