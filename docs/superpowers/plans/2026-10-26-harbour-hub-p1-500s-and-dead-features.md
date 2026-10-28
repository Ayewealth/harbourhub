# Harbour Hub P1 — Every 500 and Dead Feature

> **For the implementing engineer:** This plan is written for a skilled Django developer who has
> never seen this repository. Follow the tasks in order. Every task ends with a runnable
> verification command and a commit.
>
> **Spec:** `docs/superpowers/specs/2026-10-26-harbour-hub-connectivity-design.md` (committed `da29bd7`).
> **Phase:** P1 only. P0 is complete (`docs/superpowers/plans/P0-COMPLETE.md`); P2–P3 get their own plans.
> **Rule:** never delete or reset existing data. Add → backfill → verify → constrain.

---

## Goal

Make every endpoint in §2.2 of the spec either work or fail with a deliberate `4xx`. No route may
return `500`, no scheduled task may raise `FieldError`, and no feature may be silently dead.

Concretely, after this phase:

1. The 08:00 rental-reminder task runs against the real `OrderItem` rental fields.
2. The analytics overview can be requested twice in five minutes without a serialisation error.
3. The admin payments page and both dashboard stat cards load.
4. Store-less listings stay visible, a listing with live orders cannot be deleted, and publish
   cannot dereference a missing store.
5. `POST /orders/<id>/extend-rental/` extends the rental items and returns the legacy shape.
6. `POST /orders/<id>/ship/` requires a carrier and tracking id and moves the order to
   `item_dispatched` instead of jumping straight to `fulfilled`.
7. The orders list returns integer `order_id` plus a total; the tracking page returns amounts.
8. Sellers can read the order timeline; buyers can cancel a paid order and get a refund.
9. Reviews support edit/delete and require a paid order.
10. Sales counts and recent-sales widgets survive the whole paid lifecycle.
11. One schema file exists and CI validates it.
12. No debug `print` remains in application code.

## Scope boundaries

- **In scope:** D-15 … D-30 and D-32 from §2.2 of the spec.
- **Out of scope (P2):** one-cart-item-one-order checkout redesign, store-authoritative seller
  derivation, commission/currency snapshots, 50/50 tranches, `RentalExtension` payment,
  notification dispatcher, `release_pending_earnings_task` hardening, `process_payout_task`
  idempotency, ad-hoc root scripts, N+1 cleanup.
- **Deliberate shortcut:** P1 fixes the *shape* of the order/tracking API. P2 changes the order
  grain; the serializers here must therefore read through `order.items` and never assume a
  single item.
- **No migrations are expected in P1.** If a task seems to need one, stop and re-read the spec.

---

## Working conventions

- Branch: `fix/p1-500s-and-dead-features` off `main` (which is at `8382811`).
- Python 3.11. Commands assume the repo virtualenv is active.
- Tests use PostgreSQL `test_harbour_hub` through `hb.settings_test` (see `pytest.ini`).
- Every code block is complete. Place it where stated; do not invent surrounding code.
- Commit after every task with the message given.
- Run `python manage.py check` after every edit.
- Verification for every task is:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python -m pytest -q
flake8 apps hb --select=F821 --exclude=migrations
```

- The shared factories are in `tests/factories.py`; the API client fixtures are `api_client`
  and `auth_client` in `tests/conftest.py`.

### Shared constants introduced in Task 9

Tasks 1, 7 and 9 all need the same definition of "this order counts as a sale". Create
`apps/commerce/constants.py` in Task 9 and import from it everywhere. Until Task 9, use the
literal lists given in the earlier tasks; Task 9 replaces them.

---

## Task 1 — Rental reminders read `OrderItem` rental dates (D-15)

**Why:** `send_rental_reminders_task` queries `Order.order_type` and `Order.rental_end_date`.
Neither field exists. Celery Beat raises `FieldError` every morning at 08:00 and no reminder is
ever sent.

**Files**

- Modify: `apps/notifications/tasks.py`
- Create: `tests/test_notifications.py`

### Step 1.1 — Write the failing test

```python
# tests/test_notifications.py
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.commerce.models import Order, OrderItem
from apps.notifications.models import Notification
from apps.notifications.tasks import send_rental_reminders_task

from .factories import OrderFactory, OrderItemFactory


@pytest.mark.django_db
def test_rental_reminder_uses_order_item_dates():
    today = timezone.now().date()
    order = OrderFactory(status=Order.Status.ACTIVE_HIRE)
    OrderItemFactory(
        order=order,
        purchase_type=Order.OrderType.HIRE,
        rental_start_date=today - timedelta(days=2),
        rental_end_date=today + timedelta(days=1),
        duration_days=3,
    )

    send_rental_reminders_task()

    assert Notification.objects.filter(
        recipient=order.buyer,
        notification_type="rental_reminder",
    ).exists()


@pytest.mark.django_db
def test_rental_reminder_does_not_send_for_finished_orders():
    today = timezone.now().date()
    order = OrderFactory(status=Order.Status.FULFILLED)
    OrderItemFactory(
        order=order,
        purchase_type=Order.OrderType.HIRE,
        rental_start_date=today - timedelta(days=2),
        rental_end_date=today + timedelta(days=1),
        duration_days=3,
    )

    send_rental_reminders_task()

    assert not Notification.objects.filter(
        recipient=order.buyer,
        notification_type="rental_reminder",
    ).exists()
```

Confirm it fails with `FieldError: Cannot resolve keyword 'order_type'`.

### Step 1.2 — Rewrite the task

Replace the whole body of `apps/notifications/tasks.py` with:

```python
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

import logging

logger = logging.getLogger(__name__)

# Orders whose rental clock is still running. A reminder must not fire for a
# cancelled or fulfilled order even if the stored end date happens to match.
ACTIVE_RENTAL_STATUSES = [
    "paid",
    "order_confirmed",
    "item_dispatched",
    "in_transit",
    "delivered",
    "active_hire",
]


@shared_task
def send_rental_reminders_task():
    """
    Send a reminder one and three days before each hire/lease period ends.

    Rental dates live on OrderItem, not Order: one order can contain a
    purchase plus a hire, and P2 makes one order per cart item anyway.
    Run daily via Celery Beat.
    """
    from apps.commerce.models import OrderItem
    from .utils import notify_rental_reminder

    today = timezone.now().date()

    for days in (1, 3):
        target_date = today + timedelta(days=days)
        items = (
            OrderItem.objects.filter(
                purchase_type__in=["hire", "lease"],
                rental_end_date=target_date,
                order__status__in=ACTIVE_RENTAL_STATUSES,
            )
            .select_related("order", "order__buyer", "listing")
            .order_by("order_id")
        )

        notified_order_ids = set()
        for item in items:
            # One notification per order, no matter how many hire items it has.
            if item.order_id in notified_order_ids:
                continue
            notified_order_ids.add(item.order_id)
            notify_rental_reminder(item.order, days_left=days)
            logger.info(
                "Rental reminder sent for order %s (%d days left)",
                item.order.order_number,
                days,
            )
```

### Step 1.3 — Run

```powershell
python -m pytest tests/test_notifications.py -q
```

Then the full verification block from *Working conventions*.

**Commit:** `fix(notifications): read rental dates from order items`

---

## Task 2 — Analytics overview survives its own cache (D-16)

**Why:** the view caches `{"generated_at": datetime, ...}`. On the first request DRF serialises
the datetime. On the second request the cached dict is handed straight to `Response`, bypassing
the serializer, and DRF's JSON renderer receives a raw `datetime` (plus `Decimal`). The endpoint
500s for the whole five-minute TTL.

**Files**

- Modify: `apps/analytics/views.py`
- Create: `tests/test_analytics.py`

### Step 2.1 — Write the failing test

```python
# tests/test_analytics.py
import pytest

from apps.accounts.models import User

from .factories import UserFactory


@pytest.mark.django_db
def test_analytics_overview_is_repeatable(auth_client):
    staff = UserFactory(role=User.Role.ADMIN, is_staff=True)
    client = auth_client(staff)

    first = client.get("/analytics/overview/")
    second = client.get("/analytics/overview/")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.data["generated_at"] == second.data["generated_at"]
```

Check the real route name with `python manage.py show_urls` or `apps/analytics/urls.py`; if the
overview is mounted at `/analytics/` use that path. Adjust only the URL, not the assertions.

Confirm the second request returns `500`.

### Step 2.2 — Cache the serialised representation

Replace `list` in `apps/analytics/views.py`:

```python
    def list(self, request):
        """Get comprehensive platform statistics."""
        if getattr(self, "swagger_fake_view", False):
            return Response({})  # Safe for schema generation

        cached_data = cache.get("analytics:overview_snapshot")
        if cached_data is not None:
            return Response(cached_data)

        now = timezone.now()
        last_30_days = now - timedelta(days=30)
        last_7_days = now - timedelta(days=7)
        last_90_days = now - timedelta(days=90)
        last_365_days = now - timedelta(days=365)

        payload = {
            "user_stats": self._get_user_statistics(
                last_30_days, last_7_days, last_90_days, last_365_days),
            "listing_stats": self._get_listing_statistics(
                last_30_days, last_7_days, last_90_days, last_365_days),
            "inquiry_stats": self._get_inquiry_statistics(
                last_30_days, last_7_days, last_90_days, last_365_days),
            "category_stats": self._get_category_statistics(),
            "business_stats": self._get_business_statistics(
                last_30_days, last_7_days, last_90_days, last_365_days),
            "generated_at": now,
        }

        # Serialise before caching. A raw dict containing datetime/Decimal is not
        # JSON-renderable by DRF on the next request.
        data = AnalyticsOverviewSerializer(
            payload, context={"request": request}
        ).data
        cache.set("analytics:overview_snapshot", data, 300)
        return Response(data)
```

Note `is not None`, not truthiness: an empty-but-valid payload must still be cached.

### Step 2.3 — Run

```powershell
python -m pytest tests/test_analytics.py -q
```

Then the full verification block.

**Commit:** `fix(analytics): cache serialised overview instead of raw datetimes`

---

## Task 3 — Admin payment list and dashboard cards (D-17, D-18)

**Why:** `Payment` has no `order` foreign key. The list view calls
`select_related("order", "order__seller", "order__listing")` and the search backend traverses
`order__order_number`; both raise `FieldError`. Both stat views aggregate
`Sum("order__escrow_fee")`, which cannot resolve. The payments page and the Payments/Reports
cards therefore 500.

Platform revenue must come from the seller commission (`VendorEarning.commission_amount`), not
from `Order.escrow_fee`: P0 set the buyer fee to zero, so `escrow_fee` is always `0.00`.

**Files**

- Modify: `apps/admin_panel/views.py`
- Create: `tests/test_admin_payments.py`

### Step 3.1 — Write the failing tests

```python
# tests/test_admin_payments.py
from decimal import Decimal

import pytest

from apps.accounts.models import User

from .factories import PaymentFactory, UserFactory, VendorEarningFactory


def _finance_admin():
    return UserFactory(
        role=User.Role.ADMIN,
        is_staff=True,
        admin_profile__modules=["payments_finance"],
        admin_profile__can_manage=True,
    )


@pytest.mark.django_db
def test_admin_payment_list_loads(auth_client):
    PaymentFactory(status="success", amount=Decimal("1000.00"))
    client = auth_client(_finance_admin())

    response = client.get("/admin-panel/payments/")

    assert response.status_code == 200


@pytest.mark.django_db
def test_admin_payment_list_search_loads(auth_client):
    PaymentFactory(status="success")
    client = auth_client(_finance_admin())

    response = client.get("/admin-panel/payments/", {"search": "PAY-TEST"})

    assert response.status_code == 200


@pytest.mark.django_db
def test_admin_payment_stats_use_commission(auth_client):
    earning = VendorEarningFactory(
        gross_amount=Decimal("1000.00"), commission_rate=Decimal("5.00")
    )
    client = auth_client(_finance_admin())

    response = client.get("/admin-panel/payments/stats/")

    assert response.status_code == 200
    assert Decimal(str(response.data["platform_revenue"]["value"])) == (
        earning.commission_amount
    )
```

If `UserFactory(admin_profile__...)` is unsupported by the current factory, create the
`AdminProfile` explicitly:

```python
from apps.admin_panel.models import AdminProfile

profile, _ = AdminProfile.objects.get_or_create(user=user)
profile.modules = ["payments_finance"]
profile.can_manage = True
profile.save()
```

Confirm the list and stats tests fail with `FieldError`.

### Step 3.2 — Fix the list view

In `apps/admin_panel/views.py`, replace the `AdminPaymentListView` body:

```python
class AdminPaymentListView(generics.ListAPIView):
    """Admin view of all payments/transactions."""
    permission_classes = [IsDashboardStaff, HasAdminModulePermission]
    admin_module = AdminModule.PAYMENTS_FINANCE
    admin_require_manage = False
    filter_backends = [DjangoFilterBackend, filters.SearchFilter,
                       filters.OrderingFilter]
    from apps.commerce.filters import PaymentFilter
    filterset_class = PaymentFilter
    search_fields = ["reference", "buyer__email"]

    def get_queryset(self):
        from apps.commerce.models import Payment
        return Payment.objects.select_related(
            "buyer", "checkout_session"
        ).prefetch_related(
            "checkout_session__orders"
        ).order_by("-created_at")

    def get_serializer_class(self):
        from apps.commerce.serializers import PaymentSerializer
        return PaymentSerializer
```

`Payment.checkout_session` is the only route from a payment to its orders.

### Step 3.3 — Replace the payment stats metrics

In `AdminPaymentStatsView.get`, replace only the inner `get_metrics`:

```python
        def get_metrics(start, end):
            from apps.financials.models import VendorEarning

            payments = Payment.objects.filter(
                status="success",
                created_at__gte=start,
                created_at__lte=end,
            )
            vol = payments.aggregate(t=Sum("amount"))["t"] or 0

            # Platform revenue is the seller commission. Buyers pay no fee, so
            # Order.escrow_fee is always zero.
            rev = VendorEarning.objects.filter(
                created_at__gte=start,
                created_at__lte=end,
            ).aggregate(t=Sum("commission_amount"))["t"] or 0

            payouts_paid = Payout.objects.filter(
                status="paid", created_at__gte=start, created_at__lte=end
            )
            paid_payouts = payouts_paid.aggregate(t=Sum("amount"))["t"] or 0

            payouts_pending = Payout.objects.filter(
                status__in=["requested", "processing"],
                created_at__gte=start,
                created_at__lte=end,
            )
            pend_payouts = payouts_pending.aggregate(t=Sum("amount"))["t"] or 0

            return {
                "total_volume": float(vol),
                "platform_revenue": float(rev),
                "vendor_payouts": float(paid_payouts),
                "pending_payouts": float(pend_payouts),
            }
```

Use `Decimal` rather than `float` if the surrounding response contract is changed in the same
commit; otherwise keep `float` to avoid breaking the frontend.

### Step 3.4 — Replace the report stats metric

In `AdminReportStatsView.get`, replace only its inner `get_metrics`:

```python
        def get_metrics(start, end):
            from apps.financials.models import VendorEarning

            rev = VendorEarning.objects.filter(
                created_at__gte=start,
                created_at__lte=end,
            ).aggregate(t=Sum("commission_amount"))["t"] or 0

            disputes = Dispute.objects.filter(
                status__in=["open", "under_review"],
                created_at__gte=start,
                created_at__lte=end,
            ).count()

            inquiries = QuoteRequest.objects.filter(
                created_at__gte=start,
                created_at__lte=end,
            ).count()

            return {
                "total_revenue": float(rev),
                "active_disputes": disputes,
                "new_inquiries": inquiries,
            }
```

### Step 3.5 — Run

```powershell
python -m pytest tests/test_admin_payments.py -q
```

Then the full verification block.

**Commit:** `fix(admin): query payments without the missing order relation`

---

## Task 4 — Listing visibility, delete guard, publish guard (D-19, D-20, D-21)

**Why:** `store__is_active=True` is an inner join, so a listing whose store was deleted or never
set is invisible. The delete guard is correct but only covers two order statuses. `publish`
dereferences `listing.store` without a guard.

**Files**

- Modify: `apps/listings/views.py`
- Modify: `tests/test_listings.py`

### Step 4.1 — Add the failing tests

Append to `tests/test_listings.py`:

```python
import pytest

from apps.accounts.models import User
from apps.commerce.models import Order
from apps.listings.models import Listing

from .factories import ListingFactory, OrderFactory, OrderItemFactory, UserFactory


@pytest.mark.django_db
def test_listing_without_store_stays_visible(api_client):
    listing = ListingFactory(store=None, status=Listing.Status.PUBLISHED)

    response = api_client.get("/listings/")

    ids = [row["id"] for row in response.data["results"]]
    assert listing.id in ids


@pytest.mark.django_db
def test_publish_fails_cleanly_without_a_store(api_client):
    seller = UserFactory(role=User.Role.SELLER)
    listing = ListingFactory(
        user=seller, store=None, status=Listing.Status.DRAFT
    )
    api_client.force_authenticate(user=seller)

    response = api_client.post(f"/listings/{listing.id}/publish/")

    assert response.status_code == 400
    assert "store" in response.data["error"].lower()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "order_status",
    [
        Order.Status.PAID,
        Order.Status.ORDER_CONFIRMED,
        Order.Status.ITEM_DISPATCHED,
        Order.Status.IN_TRANSIT,
        Order.Status.DELIVERED,
        Order.Status.ACTIVE_HIRE,
        Order.Status.HIRE_ENDED,
        Order.Status.ITEM_RETURNED,
    ],
)
def test_listing_with_live_order_cannot_be_deleted(api_client, order_status):
    listing = ListingFactory()
    order = OrderFactory(status=order_status, store=listing.store)
    OrderItemFactory(order=order, listing=listing)
    api_client.force_authenticate(user=listing.user)

    response = api_client.delete(f"/listings/{listing.id}/")

    assert response.status_code == 400
    assert Listing.objects.filter(pk=listing.pk).exists()
```

`ListingFactory(store=None)` will fail if the factory derives `user` from `store.user`; pass
`user=UserFactory(role=User.Role.SELLER)` explicitly in that test. `store` is non-null at the model
level after P0, so use `Listing.objects.filter(...).update(store=None)` only if the model still
allows it; otherwise assert the guard at the view level with a mocked null store. Do not weaken
the model constraint.

### Step 4.2 — Fix the queryset filters

In `apps/listings/views.py`, replace the three published+store filters in `get_queryset`:

```python
        if self.action == 'list':
            return queryset.filter(
                Q(status=Listing.Status.PUBLISHED)
                & (Q(store__is_active=True) | Q(store__isnull=True))
            )
        elif self.action in ['retrieve']:
            user = self.request.user
            public_filter = (
                Q(status=Listing.Status.PUBLISHED)
                & (Q(store__is_active=True) | Q(store__isnull=True))
            )
            if user and user.is_authenticated:
                if getattr(user, "is_admin_user", False):
                    return queryset
                return queryset.filter(public_filter | Q(user=user))
            return queryset.filter(public_filter)
```

Apply the same `Q(store__is_active=True) | Q(store__isnull=True)` shape to
`TopDealsListView`, `BestReviewedListView`, `SavedItemListView` and `SavedItemToggleView`.

### Step 4.3 — Widen the delete guard

Replace the `active_orders` block in `destroy`:

```python
        active_orders = OrderItem.objects.filter(
            listing=instance,
            order__status__in=[
                Order.Status.PENDING_PAYMENT,
                Order.Status.PAID,
                Order.Status.ORDER_CONFIRMED,
                Order.Status.ITEM_DISPATCHED,
                Order.Status.IN_TRANSIT,
                Order.Status.DELIVERED,
                Order.Status.ACTIVE_HIRE,
                Order.Status.HIRE_ENDED,
                Order.Status.ITEM_RETURNED,
            ],
        ).exists()
```

These are exactly the pre-terminal states; `FULFILLED` and `CANCELLED` stay deletable.

### Step 4.4 — Guard publish

In `publish`, replace the activity call:

```python
        if listing.store_id:
            log_store_activity(
                listing.store,
                "listing_published",
                f"{listing.title} has been published",
            )
```

Do the same for `pause` and `resume`.

### Step 4.5 — Run

```powershell
python -m pytest tests/test_listings.py -q
```

Then the full verification block.

**Commit:** `fix(listings): keep store-less listings visible and guard lifecycle actions`

---

## Task 5 — Extend rental and ship (D-22, D-23)

**Why:** `Order.rental_end_date`, `rental_start_date`, `rental_duration_days` and
`rental_days_total` were removed; they live on `OrderItem`. `OrderMarkShippedView` accepts no
body, ignores the tracking number, and jumps to `FULFILLED`, which skips delivery and breaks the
vendor's sales timeline.

**Files**

- Modify: `apps/commerce/views.py`
- Create: `tests/test_order_lifecycle.py`

### Step 5.1 — Write the failing tests

```python
# tests/test_order_lifecycle.py
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.commerce.models import Order, OrderItem

from .factories import OrderFactory, OrderItemFactory


@pytest.mark.django_db
def test_extend_rental_updates_items_and_returns_legacy_shape(auth_client):
    today = timezone.now().date()
    order = OrderFactory(status=Order.Status.ACTIVE_HIRE)
    item = OrderItemFactory(
        order=order,
        purchase_type=Order.OrderType.HIRE,
        rental_start_date=today - timedelta(days=5),
        rental_end_date=today + timedelta(days=2),
        duration_days=7,
    )
    client = auth_client(order.buyer)

    response = client.post(
        f"/commerce/orders/{order.id}/extend-rental/",
        {"duration_days": 7},
        format="json",
    )

    assert response.status_code == 200
    item.refresh_from_db()
    assert item.rental_end_date == today + timedelta(days=9)
    assert item.duration_days == 14
    assert response.data["new_end_date"] == str(today + timedelta(days=9))
    assert response.data["rental_days_total"] == 14


@pytest.mark.django_db
def test_extend_rental_rejects_a_shorter_date(auth_client):
    today = timezone.now().date()
    order = OrderFactory(status=Order.Status.ACTIVE_HIRE)
    OrderItemFactory(
        order=order,
        purchase_type=Order.OrderType.HIRE,
        rental_start_date=today - timedelta(days=5),
        rental_end_date=today + timedelta(days=2),
        duration_days=7,
    )
    client = auth_client(order.buyer)

    response = client.post(
        f"/commerce/orders/{order.id}/extend-rental/",
        {"new_end_date": str(today)},
        format="json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_ship_requires_carrier_and_tracking(auth_client):
    order = OrderFactory(status=Order.Status.PAID)
    OrderItemFactory(order=order)
    client = auth_client(order.seller)

    response = client.post(
        f"/commerce/orders/{order.id}/ship/", {}, format="json"
    )

    assert response.status_code == 400
    order.refresh_from_db()
    assert order.status == Order.Status.PAID


@pytest.mark.django_db
def test_ship_records_tracking_and_dispatches(auth_client):
    order = OrderFactory(status=Order.Status.PAID)
    OrderItemFactory(order=order)
    client = auth_client(order.seller)

    response = client.post(
        f"/commerce/orders/{order.id}/ship/",
        {"carrier": "GIG Logistics", "tracking_id": "GIG-123"},
        format="json",
    )

    assert response.status_code == 200
    order.refresh_from_db()
    assert order.status == Order.Status.ITEM_DISPATCHED
    assert order.delivery_carrier == "GIG Logistics"
    assert order.tracking_id == "GIG-123"
    assert order.activities.filter(event_type="shipped").exists()
```

Confirm both endpoints 500.

### Step 5.2 — Rewrite `OrderExtendRentalView.post`

```python
    def post(self, request, pk):
        order = get_object_or_404(
            Order.objects.filter(buyer=request.user).distinct(), pk=pk
        )
        items = list(
            order.items.filter(
                purchase_type__in=[Order.OrderType.HIRE, Order.OrderType.LEASE]
            ).order_by("rental_end_date")
        )
        if not items:
            return Response(
                {"error": "This order has no rental items to extend."},
                status=400,
            )

        duration_days = request.data.get("duration_days")
        new_end_date = request.data.get("new_end_date")
        today = timezone.now().date()

        current_end = max(
            (item.rental_end_date for item in items if item.rental_end_date),
            default=today,
        )

        if duration_days:
            try:
                duration_days = int(duration_days)
            except (TypeError, ValueError):
                return Response(
                    {"error": "duration_days must be an integer"}, status=400
                )
            if duration_days <= 0:
                return Response(
                    {"error": "duration_days must be positive"}, status=400
                )
            parsed = current_end + timedelta(days=duration_days)
        elif new_end_date:
            parsed = parse_date(new_end_date)
            if not parsed:
                return Response(
                    {"error": "Invalid date format. Use YYYY-MM-DD"},
                    status=400,
                )
        else:
            return Response(
                {"error": "new_end_date or duration_days is required"},
                status=400,
            )

        if parsed <= current_end:
            return Response(
                {"error": "New end date must be after current end date"},
                status=400,
            )

        delta = parsed - current_end
        with transaction.atomic():
            for item in items:
                item.rental_end_date = (item.rental_end_date or current_end) + delta
                item.duration_days = (item.duration_days or 0) + delta.days
                item.save(update_fields=["rental_end_date", "duration_days"])

        OrderActivity.objects.create(
            order=order,
            event_type=OrderActivity.EventType.RENTAL_EXTENDED,
            message=f"Rental extended to {parsed}.",
        )

        return Response({
            "message": "Rental extended successfully",
            "new_end_date": str(parsed),
            "rental_days_total": max(
                (item.rental_days_total or 0 for item in items), default=0
            ),
        })
```

`get_object_or_404` on `Order.objects.filter(buyer=user).distinct()` preserves the old 404 for a
foreign order and avoids the duplicate rows the old `items__` join produced.

### Step 5.3 — Rewrite `OrderMarkShippedView.post`

```python
    def post(self, request, pk):
        order = get_object_or_404(Order, pk=pk, seller=request.user)

        if order.status not in (Order.Status.PAID, Order.Status.ORDER_CONFIRMED):
            return Response(
                {"error": "Only paid or confirmed orders can be shipped"},
                status=400,
            )

        carrier = (request.data.get("carrier") or "").strip()
        tracking_id = (request.data.get("tracking_id") or "").strip()
        if not carrier or not tracking_id:
            return Response(
                {"error": "carrier and tracking_id are required"},
                status=400,
            )

        with transaction.atomic():
            order.status = Order.Status.ITEM_DISPATCHED
            order.delivery_carrier = carrier
            order.tracking_id = tracking_id
            order.save(
                update_fields=["status", "delivery_carrier", "tracking_id"]
            )
            OrderActivity.objects.create(
                order=order,
                event_type=OrderActivity.EventType.SHIPPED,
                message=f"Dispatched via {carrier}. Tracking: {tracking_id}.",
            )

        notify_order_shipped(order)

        return Response({
            "message": "Order marked as shipped",
            "status": order.status,
            "carrier": carrier,
            "tracking_id": tracking_id,
        })
```

Update the `@extend_schema` decorator above it: replace `request=None` with an inline serializer
for `carrier` and `tracking_id` (both `CharField(required=True)`), and add those two fields to the
200 response serializer.

### Step 5.4 — Run

```powershell
python -m pytest tests/test_order_lifecycle.py -q
```

Then the full verification block.

**Commit:** `fix(commerce): extend rentals on items and ship with tracking`

---

## Task 6 — Order list and tracking contracts (D-24, D-25)

**Why:** the orders page reads `order_id` and expects an integer; the list serializer emits the
string `order_number` and no total. The tracking serializer declares four `monetary_fields` that
are absent from `Meta.fields`, so the page has no amounts.

**Files**

- Modify: `apps/commerce/serializers.py`
- Create: `tests/test_order_serializers.py`

### Step 6.1 — Write the failing tests

```python
# tests/test_order_serializers.py
from decimal import Decimal

import pytest

from apps.commerce.models import Order

from .factories import OrderFactory, OrderItemFactory


@pytest.mark.django_db
def test_my_orders_returns_integer_id_and_total(auth_client):
    order = OrderFactory(total_amount=Decimal("1234.00"))
    OrderItemFactory(order=order)
    client = auth_client(order.buyer)

    response = client.get("/commerce/orders/my-orders/")

    row = response.data["results"][0]
    assert row["order_id"] == order.id
    assert isinstance(row["order_id"], int)
    assert row["order_number"] == order.order_number
    assert Decimal(str(row["total_amount"])) == Decimal("1234.00")


@pytest.mark.django_db
def test_tracking_detail_includes_amounts(auth_client):
    order = OrderFactory(
        total_amount=Decimal("1234.00"),
        subtotal=Decimal("1200.00"),
        delivery_fee=Decimal("34.00"),
        escrow_fee=Decimal("0.00"),
    )
    OrderItemFactory(order=order)
    client = auth_client(order.buyer)

    response = client.get(f"/commerce/orders/{order.id}/tracking/")

    assert response.status_code == 200
    assert Decimal(str(response.data["total_amount"])) == Decimal("1234.00")
    assert Decimal(str(response.data["subtotal"])) == Decimal("1200.00")
    assert Decimal(str(response.data["delivery_fee"])) == Decimal("34.00")
    assert Decimal(str(response.data["escrow_fee"])) == Decimal("0.00")
```

### Step 6.2 — Fix the list summary serializer

In `apps/commerce/serializers.py`, replace `OrderListTrackingSummarySerializer`:

```python
class OrderListTrackingSummarySerializer(serializers.ModelSerializer):
    order_id = serializers.IntegerField(source="id", read_only=True)
    listing_title = serializers.SerializerMethodField()
    seller_name = serializers.CharField(source="store.name", default="")
    buyer_name = serializers.CharField(source="buyer.full_name", default="")
    last_event = serializers.SerializerMethodField()
    last_event_at = serializers.SerializerMethodField()
    carrier = serializers.CharField(source="delivery_carrier", read_only=True)

    class Meta:
        model = Order
        fields = (
            "order_id",
            "order_number",
            "listing_title",
            "seller_name",
            "buyer_name",
            "status",
            "total_amount",
            "last_event",
            "last_event_at",
            "created_at",
            "tracking_id",
            "delivery_carrier",
            "carrier",
        )

    @extend_schema_field(serializers.CharField())
    def get_listing_title(self, obj):
        # P2 changes the order grain; read through items now so this survives it.
        item = obj.items.select_related("listing").first()
        return item.listing.title if item and item.listing else ""

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_last_event(self, obj):
        activities = list(obj.activities.all())
        return activities[0].message if activities else "Order Placed"

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_last_event_at(self, obj):
        activities = list(obj.activities.all())
        return activities[0].created_at if activities else obj.created_at
```

The `get_last_event` change matters: the old code issued two queries per row and relied on
`Meta.ordering`. Read once.

Add `prefetch_related("items__listing", "activities")` and
`select_related("store", "buyer")` to both `BuyerMyOrdersListView.get_queryset` and
`SellerStoreOrdersListView.get_queryset` so the serializer does not N+1.

### Step 6.3 — Fix the tracking detail serializer

In `OrderTrackingDetailSerializer`:

* replace `order_id = serializers.CharField(source="order_number")` with
  `order_id = serializers.IntegerField(source="id", read_only=True)`;
* replace `listing_title = serializers.CharField(source="listing.title", default="")` with a
  `SerializerMethodField` identical to the one above;
* add `"order_number"` and the four monetary fields to `Meta.fields`.

```python
class OrderTrackingDetailSerializer(CurrencyConverterMixin, serializers.ModelSerializer):
    monetary_fields = ["total_amount", "subtotal", "delivery_fee", "escrow_fee"]

    order_id = serializers.IntegerField(source="id", read_only=True)
    listing_title = serializers.SerializerMethodField()
    buyer = serializers.SerializerMethodField()
    seller = serializers.SerializerMethodField()
    estimated_delivery = serializers.SerializerMethodField()
    dispute = serializers.SerializerMethodField()
    timeline = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = (
            "order_id",
            "order_number",
            "status",
            "listing_title",
            "buyer",
            "seller",
            "total_amount",
            "subtotal",
            "delivery_fee",
            "escrow_fee",
            "created_at",
            "estimated_delivery",
            "dispute",
            "timeline",
            "tracking_id",
            "delivery_carrier",
        )
```

Keep the existing `get_buyer`, `get_seller`, `get_dispute` and `get_timeline` methods unchanged.

Add `prefetch_related("items__listing", "activities", "disputes")` in
`OrderTrackingDetailView.get_object` before returning the instance.

### Step 6.4 — Run

```powershell
python -m pytest tests/test_order_serializers.py -q
```

Then the full verification block.

**Commit:** `fix(commerce): return integer order ids and totals from order APIs`

---

## Task 7 — Seller timeline and paid cancellation (D-27, D-28)

**Why:** `OrderActivityListView` filters `buyer=user` unless staff, so the vendor who owns the
order gets a 404 on its own timeline. `OrderDetailView.post` only allows cancellation while the
order is `draft` or `pending_payment`; a buyer with a paid order has no cancellation or refund
path.

**Files**

- Modify: `apps/commerce/views.py`
- Create: `tests/test_order_cancel.py`

### Step 7.1 — Write the failing tests

```python
# tests/test_order_cancel.py
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.commerce.models import Order, Payment

from .factories import OrderFactory, OrderItemFactory, PaymentFactory


@pytest.mark.django_db
def test_seller_can_read_the_order_timeline(auth_client):
    order = OrderFactory()
    OrderItemFactory(order=order)
    client = auth_client(order.seller)

    response = client.get(f"/commerce/orders/{order.id}/activity/")

    assert response.status_code == 200


@pytest.mark.django_db
def test_buyer_can_cancel_a_paid_order_and_request_a_refund(auth_client):
    order = OrderFactory(
        status=Order.Status.PAID, total_amount=Decimal("1000.00")
    )
    OrderItemFactory(order=order)
    PaymentFactory(
        checkout_session=order.checkout_session,
        buyer=order.buyer,
        amount=Decimal("1000.00"),
        status=Payment.Status.SUCCESS,
    )
    client = auth_client(order.buyer)

    with patch("apps.commerce.services.refunds.initiate_refund") as gateway:
        gateway.return_value = {"reference": "RF-TEST-1", "status": "processing"}
        response = client.post(
            f"/commerce/orders/{order.id}/cancel/",
            {"reason": "Changed my mind"},
            format="json",
        )

    assert response.status_code == 202
    order.refresh_from_db()
    assert order.refund_requests.count() == 1
    assert order.status == Order.Status.PAID  # cancelled when the gateway confirms
```

If `Order` has no `refund_requests` reverse relation, assert through the refund model:

```python
from apps.commerce.models import Refund

refund = Refund.objects.get(payment__checkout_session=order.checkout_session)
assert refund.status == Refund.Status.REQUESTED
```

Do not assert a status change on the order: `finalize_refund` owns that transition.

### Step 7.2 — Fix the activity queryset

Replace `OrderActivityListView.get_queryset`:

```python
    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return OrderActivity.objects.none()
        order_id = self.kwargs['pk']
        user = self.request.user
        queryset = Order.objects.filter(
            Q(buyer=user) | Q(seller=user) | Q(store__user=user)
        )
        if getattr(user, 'is_admin_user', False) or user.is_staff:
            queryset = Order.objects.all()
        order = get_object_or_404(queryset.distinct(), pk=order_id)
        return OrderActivity.objects.filter(
            order=order
        ).select_related("order").order_by('-created_at')
```

### Step 7.3 — Add the paid cancellation branch

Replace `OrderDetailView.post`:

```python
    def post(self, request, pk=None):
        """Cancel an unpaid order, or request a refund for a paid one."""
        order = self.get_object()
        if request.user not in (order.buyer, order.seller):
            return Response({'error': 'Permission denied'}, status=403)

        if order.status in (Order.Status.DRAFT, Order.Status.PENDING_PAYMENT):
            order.status = Order.Status.CANCELLED
            order.save(update_fields=['status'])
            notify_order_cancelled(order, cancelled_by=request.user)
            OrderActivity.objects.create(
                order=order,
                event_type=OrderActivity.EventType.ORDER_CANCELLED,
                message="Order has been cancelled.",
            )
            return Response({'message': 'Order cancelled successfully'})

        if order.status != Order.Status.PAID:
            return Response(
                {'error': 'Order cannot be cancelled at this stage'}, status=400
            )

        payment = Payment.objects.filter(
            checkout_session=order.checkout_session,
            status=Payment.Status.SUCCESS,
        ).first()
        if payment is None:
            return Response(
                {'error': 'No successful payment found for this order'}, status=400
            )

        from .services.refunds import RefundError, request_refund
        reason = (request.data.get('reason') or 'Order cancelled by customer').strip()
        try:
            refund = request_refund(
                payment, payment.amount, reason, actor=request.user
            )
        except RefundError as exc:
            return Response({'error': str(exc)}, status=400)

        OrderActivity.objects.create(
            order=order,
            event_type=OrderActivity.EventType.ORDER_REFUNDED,
            message=f"Refund requested: {reason}.",
        )
        return Response(
            {
                'message': 'Refund requested. The order will be cancelled once the gateway confirms.',
                'refund_id': refund.id,
                'refund_status': refund.status,
            },
            status=202,
        )
```

Add `from .models import ... Refund` is not needed in the view; the service returns it. Ensure
`Payment` is already imported (it is, line 37).

### Step 7.4 — Run

```powershell
python -m pytest tests/test_order_cancel.py -q
```

Then the full verification block.

**Commit:** `fix(commerce): let sellers read timelines and buyers refund paid orders`

---

## Task 8 — Review CRUD and paid-order gate (D-26)

**Why:** reviews are create-only, so a typo is permanent, and anyone can post a review of any
listing without ever buying it. Both destroy trust in the rating averages used by
`TopDealsListView` and `BestReviewedListView`.

**Files**

- Create: `apps/reviews/permissions.py`
- Modify: `apps/reviews/serializers.py`
- Modify: `apps/reviews/views.py`
- Modify: `apps/reviews/urls.py`
- Create: `tests/test_reviews.py`

### Step 8.1 — Write the failing tests

```python
# tests/test_reviews.py
from decimal import Decimal

import pytest

from apps.commerce.models import Order

from .factories import ListingFactory, OrderFactory, OrderItemFactory, StoreFactory, UserFactory


@pytest.mark.django_db
def test_review_requires_a_paid_order(auth_client):
    listing = ListingFactory()
    outsider = UserFactory()
    client = auth_client(outsider)

    response = client.post(
        "/reviews/listings/",
        {"listing": listing.id, "rating": 5, "comment": "Great"},
        format="json",
    )

    assert response.status_code == 400
    assert "purchase" in str(response.data).lower() or "order" in str(response.data).lower()


@pytest.mark.django_db
def test_buyer_with_paid_order_can_review(auth_client):
    listing = ListingFactory()
    buyer = UserFactory()
    order = OrderFactory(
        buyer=buyer, store=listing.store, status=Order.Status.PAID
    )
    OrderItemFactory(order=order, listing=listing)
    client = auth_client(buyer)

    response = client.post(
        "/reviews/listings/",
        {"listing": listing.id, "rating": 5, "comment": "Great"},
        format="json",
    )

    assert response.status_code == 201


@pytest.mark.django_db
def test_reviewer_can_edit_and_delete(auth_client):
    listing = ListingFactory()
    buyer = UserFactory()
    order = OrderFactory(buyer=buyer, store=listing.store, status=Order.Status.FULFILLED)
    OrderItemFactory(order=order, listing=listing)
    client = auth_client(buyer)
    created = client.post(
        "/reviews/listings/",
        {"listing": listing.id, "rating": 4, "comment": "Good"},
        format="json",
    ).data

    patched = client.patch(
        f"/reviews/listings/{created['id']}/",
        {"rating": 5, "comment": "Better"},
        format="json",
    )
    deleted = client.delete(f"/reviews/listings/{created['id']}/")

    assert patched.status_code == 200
    assert patched.data["rating"] == 5
    assert deleted.status_code == 204


@pytest.mark.django_db
def test_other_user_cannot_edit_a_review(auth_client):
    listing = ListingFactory()
    buyer = UserFactory()
    order = OrderFactory(buyer=buyer, store=listing.store, status=Order.Status.PAID)
    OrderItemFactory(order=order, listing=listing)
    created = auth_client(buyer).post(
        "/reviews/listings/",
        {"listing": listing.id, "rating": 4, "comment": "Good"},
        format="json",
    ).data
    client = auth_client(UserFactory())

    response = client.patch(
        f"/reviews/listings/{created['id']}/", {"rating": 1}, format="json"
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_store_review_requires_a_paid_order_from_that_store(auth_client):
    store = StoreFactory()
    listing = ListingFactory(store=store, user=store.user)
    buyer = UserFactory()
    order = OrderFactory(buyer=buyer, store=store, status=Order.Status.DELIVERED)
    OrderItemFactory(order=order, listing=listing)
    client = auth_client(buyer)

    response = client.post(
        "/reviews/stores/",
        {"store": store.id, "rating": 5, "comment": "Great vendor"},
        format="json",
    )

    assert response.status_code == 201
```

### Step 8.2 — Add the permission class

```python
# apps/reviews/permissions.py
from rest_framework import permissions


class IsReviewerOrReadOnly(permissions.BasePermission):
    """Anyone may read; only the reviewer may edit or delete."""

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return obj.reviewer_id == request.user.id
```

### Step 8.3 — Add update serializers and the paid-order gate

In `apps/reviews/serializers.py`, import the commerce models at the top:

```python
from apps.commerce.models import Order, OrderItem
```

Add a shared helper:

```python
PAID_STATUSES = [
    Order.Status.PAID,
    Order.Status.ORDER_CONFIRMED,
    Order.Status.ITEM_DISPATCHED,
    Order.Status.IN_TRANSIT,
    Order.Status.DELIVERED,
    Order.Status.ACTIVE_HIRE,
    Order.Status.HIRE_ENDED,
    Order.Status.ITEM_RETURNED,
    Order.Status.FULFILLED,
]


def _has_paid_order(user, *, listing=None, store=None):
    items = OrderItem.objects.filter(
        order__buyer=user,
        order__status__in=PAID_STATUSES,
    )
    if listing is not None:
        items = items.filter(listing=listing)
    if store is not None:
        items = items.filter(listing__store=store)
    return items.exists()
```

In `ListingReviewCreateSerializer.validate`, replace the duplicate check block so the order gate
runs first:

```python
    def validate(self, attrs):
        request = self.context.get("request")
        listing = attrs.get("listing")
        if request and request.user.is_authenticated and listing:
            if listing.user_id == request.user.id:
                raise serializers.ValidationError(
                    "You cannot review your own listing."
                )
            if not _has_paid_order(request.user, listing=listing):
                raise serializers.ValidationError(
                    "You can only review a listing you have purchased."
                )
            if ListingReview.objects.filter(
                listing=listing, reviewer=request.user
            ).exists():
                raise serializers.ValidationError(
                    "You have already reviewed this listing."
                )
        return attrs
```

In `StoreReviewCreateSerializer.validate`, do the same with
`_has_paid_order(request.user, store=store)` and the message
`"You can only review a store you have purchased from."`.

Add two update serializers at the end of the file:

```python
class ListingReviewUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingReview
        fields = ("rating", "comment")


class StoreReviewUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = StoreReview
        fields = ("rating", "comment")
```

### Step 8.4 — Add retrieve/update/delete views

Append to `apps/reviews/views.py`:

```python
from rest_framework import generics, permissions

from .permissions import IsReviewerOrReadOnly
from .serializers import (
    ListingReviewUpdateSerializer,
    StoreReviewUpdateSerializer,
)


class ListingReviewDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsReviewerOrReadOnly]
    queryset = ListingReview.objects.select_related("reviewer", "listing")

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return ListingReviewUpdateSerializer
        return ListingReviewSerializer


class StoreReviewDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsReviewerOrReadOnly]
    queryset = StoreReview.objects.select_related("reviewer", "store")

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return StoreReviewUpdateSerializer
        return StoreReviewSerializer
```

Import the base serializers in the same block (`ListingReviewSerializer`,
`StoreReviewSerializer` are already imported at the top of the file; keep one import block).

### Step 8.5 — Register the routes

```python
# apps/reviews/urls.py
from django.urls import path

from .views import (
    ListingReviewDetailView,
    ListingReviewListCreateView,
    StoreReviewDetailView,
    StoreReviewListCreateView,
)

urlpatterns = [
    path("listings/", ListingReviewListCreateView.as_view(), name="review-listing-list-create"),
    path("listings/<int:pk>/", ListingReviewDetailView.as_view(), name="review-listing-detail"),
    path("stores/", StoreReviewListCreateView.as_view(), name="review-store-list-create"),
    path("stores/<int:pk>/", StoreReviewDetailView.as_view(), name="review-store-detail"),
]
```

### Step 8.6 — Run

```powershell
python -m pytest tests/test_reviews.py -q
```

Then the full verification block.

**Commit:** `feat(reviews): require a paid order and allow edit and delete`

---

## Task 9 — Sales counts across the paid lifecycle (D-29)

**Why:** `Store.sales_count`, `RecentSalesView` and `PublicRecentSalesView` only count `PAID` and
`FULFILLED`. As soon as a seller ships, the sale disappears from its own dashboard until
delivery completes. The lifecycle has ten paid states.

**Files**

- Create: `apps/commerce/constants.py`
- Modify: `apps/store/models.py`
- Modify: `apps/commerce/views.py`
- Modify: `apps/listings/views.py`
- Modify: `apps/analytics/views.py`
- Modify: `apps/reviews/serializers.py`
- Create: `tests/test_sales_counts.py`

### Step 9.1 — Add the constant

```python
# apps/commerce/constants.py
from .models import Order

# States in which money has been captured and the sale is still real.
# CANCELLED is excluded. DRAFT/PENDING_PAYMENT are excluded.
SALES_STATUSES = [
    Order.Status.PAID,
    Order.Status.ORDER_CONFIRMED,
    Order.Status.ITEM_DISPATCHED,
    Order.Status.IN_TRANSIT,
    Order.Status.DELIVERED,
    Order.Status.ACTIVE_HIRE,
    Order.Status.HIRE_ENDED,
    Order.Status.ITEM_RETURNED,
    Order.Status.FULFILLED,
]

# States in which the rental clock is still running.
ACTIVE_RENTAL_STATUSES = [
    Order.Status.PAID,
    Order.Status.ORDER_CONFIRMED,
    Order.Status.ITEM_DISPATCHED,
    Order.Status.IN_TRANSIT,
    Order.Status.DELIVERED,
    Order.Status.ACTIVE_HIRE,
]

# States that still block deleting the listing behind them.
LIVE_ORDER_STATUSES = [
    Order.Status.PENDING_PAYMENT,
    *SALES_STATUSES,
]
```

### Step 9.2 — Write the failing test

```python
# tests/test_sales_counts.py
import pytest

from apps.commerce.models import Order

from .factories import ListingFactory, OrderFactory, OrderItemFactory


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status",
    [
        Order.Status.PAID,
        Order.Status.ORDER_CONFIRMED,
        Order.Status.ITEM_DISPATCHED,
        Order.Status.IN_TRANSIT,
        Order.Status.DELIVERED,
        Order.Status.ACTIVE_HIRE,
        Order.Status.HIRE_ENDED,
        Order.Status.ITEM_RETURNED,
        Order.Status.FULFILLED,
    ],
)
def test_sales_count_includes_every_paid_state(status):
    listing = ListingFactory()
    OrderFactory(store=listing.store, status=status)

    assert listing.store.sales_count == 1


@pytest.mark.django_db
def test_recent_sales_survives_shipping(auth_client):
    listing = ListingFactory()
    order = OrderFactory(
        store=listing.store, seller=listing.store.user, status=Order.Status.ITEM_DISPATCHED
    )
    OrderItemFactory(order=order, listing=listing)
    client = auth_client(listing.store.user)

    response = client.get("/commerce/orders/recent-sales/")

    assert [row["id"] for row in response.data] == [order.id]
```

### Step 9.3 — Use the constant everywhere

* `apps/store/models.py` `sales_count`: replace the status list with
  `from apps.commerce.constants import SALES_STATUSES` and `status__in=SALES_STATUSES`.
* `apps/commerce/views.py` `RecentSalesView.get_queryset`: use `SALES_STATUSES`.
* `apps/listings/views.py` `PublicRecentSalesView.get_queryset`: use `SALES_STATUSES`.
* `apps/analytics/views.py` `_get_business_statistics.get_rev`: use `SALES_STATUSES`.
* `apps/reviews/serializers.py`: delete the local `PAID_STATUSES` and import
  `SALES_STATUSES` instead.
* `apps/notifications/tasks.py`: replace the local `ACTIVE_RENTAL_STATUSES` with the constant.
* `apps/listings/views.py` `destroy`: use `LIVE_ORDER_STATUSES`.

Import at module level where that cannot create a cycle:

```python
from apps.commerce.constants import SALES_STATUSES
```

`apps/commerce/constants.py` imports `apps.commerce.models`, so `apps/commerce/views.py`,
`apps/store/models.py` and `apps/listings/views.py` are safe. Inside `apps/store/models.py`, the
import must stay inside the `sales_count` property because `store` is imported by
`commerce.models`; a module-level import would cycle. Keep it local there.

### Step 9.4 — Run

```powershell
python -m pytest tests/test_sales_counts.py -q
```

Then the full verification block.

**Commit:** `fix(commerce): count sales across the full paid lifecycle`

---

## Task 10 — One schema, validated in CI (D-30)

**Why:** `schema.yaml` is zero bytes and `schema.yml` is a stale 430 KB copy. Nobody can tell
which is authoritative, and nothing proves the committed schema still generates.

**Files**

- Delete: `schema.yaml`
- Modify: `schema.yml` (regenerate)
- Create: `tests/test_schema.py`
- Modify: `.github/workflows/ci.yml`

### Step 10.1 — Delete the empty file and regenerate

```powershell
Remove-Item schema.yaml
python manage.py spectacular --file schema.yml --validate
```

### Step 10.2 — Add a test that the schema generates

```python
# tests/test_schema.py
import pytest
from drf_spectacular.generators import SchemaGenerator


@pytest.mark.django_db
def test_openapi_schema_generates():
    schema = SchemaGenerator().get_schema(request=None, public=True)

    assert schema["openapi"].startswith("3.")
    assert "/commerce/orders/" in schema["paths"]
```

### Step 10.3 — Keep the CI gate explicit

The CI workflow already runs
`python manage.py spectacular --file /tmp/schema.yml --validate`. Replace that step with:

```yaml
      - name: OpenAPI schema
        run: python manage.py spectacular --file schema.yml --validate
```

This writes to the workspace, which means a schema regression fails the build at the same place
developers reproduce locally. Do not commit the regenerated file from CI.

### Step 10.4 — Run

```powershell
python -m pytest tests/test_schema.py -q
```

Then the full verification block.

**Commit:** `chore: keep one OpenAPI schema and validate it in CI`

---

## Task 11 — Remove the debug print (D-32)

**Why:** `print("documents_data:", documents_data)` was removed from
`apps/listings/serializers.py` during P0, but `apps/listings/tasks.py` still prints on every
scheduled run, polluting production logs and leaking listing payload shape.

**Files**

- Modify: `apps/listings/tasks.py`

### Step 11.1 — Replace the print with structured logging

```python
import logging

logger = logging.getLogger(__name__)
```

inside `expire_listings_task`, replace:

```python
    print("Running expire_listings_task …")
```

with:

```python
    logger.info("Running expire_listings_task")
```

Search the app tree for any remaining `print(` and convert each one the same way:

```powershell
Select-String -Path apps/*.py, apps/*/*.py -Pattern "print\("
```

Only `apps/commerce/tests_comprehensive.py` may keep prints (it is a test module, not production
code); convert them to `logger.debug` if the module is imported by pytest.

### Step 11.2 — Run

```powershell
Select-String -Path apps/*.py, apps/*/*.py -Pattern "print\("
```

Then the full verification block.

**Commit:** `chore(listings): replace debug print with logging`

---

## Task 12 — Route smoke test (exit criteria)

**Why:** P1 is only done when a single test can prove that no route 500s. This test resolves every
API pattern, substitutes safe values for path parameters, issues an authenticated `GET`, and
asserts the status is below `500`.

**Files**

- Create: `tests/test_route_smoke.py`

### Step 12.1 — Add the smoke test

```python
# tests/test_route_smoke.py
import re
import uuid

import pytest
from django.urls import URLPattern, URLResolver, get_resolver

from apps.accounts.models import User

from .factories import UserFactory

# Routes that must not be probed with GET: they mutate, call an external
# gateway, or are HTML-only.
SKIP_PREFIXES = (
    "/admin/",
    "/api/schema/",
    "/api/docs/",
    "/api/redoc/",
    "/commerce/payment/",
    "/commerce/checkout/",
    "/auth/logout",
)

PARAM_VALUES = {
    "int": "1",
    "str": "sample",
    "slug": "sample",
    "uuid": str(uuid.uuid4()),
}


def _walk(patterns, prefix=""):
    for entry in patterns:
        route = prefix + str(entry.pattern)
        if isinstance(entry, URLResolver):
            yield from _walk(entry.url_patterns, route)
        elif isinstance(entry, URLPattern):
            yield route


def _materialise(route):
    def replace(match):
        converter = match.group(1)
        return PARAM_VALUES.get(converter, "sample")

    path = re.sub(r"<(?:(int|str|slug|uuid):)?[^>]+>", replace, route)
    if not path.startswith("/"):
        path = "/" + path
    return path


@pytest.mark.django_db
def test_every_gettable_route_returns_below_500(api_client):
    admin = UserFactory(role=User.Role.ADMIN, is_staff=True, is_superuser=True)
    api_client.force_authenticate(user=admin)

    failures = []
    for route in _walk(get_resolver().url_patterns):
        path = _materialise(route)
        if any(path.startswith(prefix) for prefix in SKIP_PREFIXES):
            continue
        response = api_client.get(path)
        if response.status_code >= 500:
            failures.append((path, response.status_code))

    assert failures == []
```

This asserts a *subset* of methods. The point is to catch import-time and queryset errors, which
is where every P1 defect lived. Mutation paths are covered by Tasks 1–9.

### Step 12.2 — Triage any failure

A `500` here is a real P1 regression, not a flaky test. Typical causes:

* a serializer referencing a removed field;
* a `select_related` naming a non-existent relation;
* a viewset whose `get_queryset` runs at import time.

Fix the cause; do not add the path to `SKIP_PREFIXES` unless it genuinely needs a different HTTP
method.

### Step 12.3 — Run

```powershell
python -m pytest tests/test_route_smoke.py -q
```

Then the full verification block.

**Commit:** `test: smoke every GET route for 500s`

---

## Final verification

Run the complete gate:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python -m pytest -q
flake8 apps hb --select=F821 --exclude=migrations
python manage.py spectacular --file schema.yml --validate
```

Expected: `check` clean, no pending migrations, every test green, no undefined names, schema valid.

Write `docs/superpowers/plans/P1-COMPLETE.md` with:

* the commit for each task;
* the final pytest count;
* the list of endpoints proven by `test_route_smoke.py`;
* anything still requiring staging (for example a real Paystack refund webhook);
* the P2 hand-off: checkout grain, seller derivation, commission/currency snapshots, tranches,
  `RentalExtension` payment, notification dispatcher.
