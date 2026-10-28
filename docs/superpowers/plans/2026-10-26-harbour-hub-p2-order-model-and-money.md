# Harbour Hub P2 — Order Model and Money Flow

> **For the implementing engineer:** This plan assumes you have read P0 and P1 and that both are
> complete. Follow the tasks in order. Every task ends with a runnable verification command and a
> commit. Do not skip the data-safety steps: production/mock data is live and must be reconciled,
> never reset.
>
> **Spec:** `docs/superpowers/specs/2026-10-26-harbour-hub-connectivity-design.md` §3–§7 and Phase P2.
> **Previous phases:** `P0-COMPLETE.md`, `P1-COMPLETE.md`.
> **Rule:** add → backfill → verify → constrain. No `flush`, no `--fake`, no dropping tables.

---

## Goal

P1 fixed the *shape* of the order APIs. P2 fixes the **grain, the vendor, and the money**:

1. One cart item creates exactly one `Order` with exactly one `OrderItem`.
2. The `Store` is the authoritative vendor; `Order.seller` is always derived from `store.user`.
3. Buyers pay `subtotal + delivery_fee` and nothing else. The platform earns a seller-side
   commission that is snapshotted per order.
4. Currency is converted once at checkout and the rate is stored on the item.
5. Earnings release in two 50/50 tranches; a vendor can withdraw the first tranche while the
   second is held.
6. Wallets are per store and payouts are backed by `PayoutAllocation` rows.
7. Rental extensions are paid objects; dates change only after payment.
8. Refunds reverse earnings without leaving a phantom balance.
9. Every notification event can reach in-app, email, SMS, push, and the staff webhook.
10. Every status change goes through one service function.

### Exit criteria (from the spec)

- A cart with three items from three stores creates three orders, each with one item.
- A cart with three items from one store still creates three orders.
- Buyer total equals subtotal + delivery, with zero fees.
- Platform revenue equals the sum of commissions, not buyer fees.
- 50% becomes available on day 7 and the remainder on completion.
- A vendor can withdraw the first tranche while the second is held.
- A rental extension changes dates only after payment.
- A refund marks the earning reversed and does not leave a phantom balance.

---

## Working conventions

- Branch: `fix/p2-order-model-and-money` off `main`.
- Python 3.11; run inside the repo virtualenv.
- Tests use PostgreSQL `test_harbour_hub` (`hb.settings_test`, `pytest.ini`). Never switch to SQLite.
- Full gate after every task:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python -m pytest -q
python -m flake8 apps hb --select=F821 --exclude=migrations
python manage.py spectacular --file schema.yml --validate
```

- `flake8` is not on `PATH` in this shell; always use `python -m flake8`.
- Commit after every task with the message given.
- Every migration is committed with the task that introduces it.

### Commission base — resolve the spec ambiguity up front

The worked example in §3.6 is authoritative: commission is charged on **goods only**
(`order.subtotal`), and the delivery fee passes to the vendor in full. Therefore:

```
gross_amount      = order.subtotal + order.delivery_fee
commission_amount = money(order.subtotal * commission_rate / 100)
net_amount        = gross_amount - commission_amount
```

`VendorEarning.save()` must **stop** auto-computing commission from `gross_amount`, because that
would charge commission on delivery. Commission is computed explicitly in
`accrue_earning`/`apply_rental_extension`. Task 6 changes the model and factory.

### Data safety for Task 2

`Order.store` is currently `null=True`. Some historical orders may have no store. Task 2 adds a
backfill command and a data migration that:

1. sets `store` from the first `OrderItem.listing.store`;
2. falls back to `seller.store`;
3. refuses to apply the `NOT NULL` constraint while any order is still unresolved, printing the
   offending order numbers so an operator can fix them.

Never invent a placeholder store.

---

## Task 1 — Decimal-native currency helpers

**Why:** checkout, earnings, wallets, payouts and refunds must never go through
`convert_currency`, which returns a `float` and silently falls back to `1.0` when a rate is
missing. A missing rate at checkout must be a `400`, not a wrong price.

**Files**

- Modify: `apps/core/currency.py`
- Create: `tests/test_currency.py`

### Step 1.1 — Write the failing tests

```python
# tests/test_currency.py
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.core.currency import (
    CurrencyRateUnavailable,
    convert_from_ngn,
    convert_to_ngn,
    money,
)


def test_money_rounds_half_up():
    assert money("10.005") == Decimal("10.01")
    assert money(None) == Decimal("0.00")
    assert money(Decimal("2.344")) == Decimal("2.34")


@patch("apps.core.currency.get_exchange_rates")
def test_convert_to_ngn_uses_usd_base(rates):
    rates.return_value = {"USD": 1.0, "NGN": 1500.0, "GBP": 0.5}
    assert convert_to_ngn(Decimal("2.00"), "USD") == Decimal("3000.00")
    # GBP -> USD -> NGN: 2 / 0.5 * 1500
    assert convert_to_ngn(Decimal("2.00"), "GBP") == Decimal("6000.00")


@patch("apps.core.currency.get_exchange_rates")
def test_convert_from_ngn_round_trips(rates):
    rates.return_value = {"USD": 1.0, "NGN": 1500.0}
    assert convert_from_ngn(Decimal("3000.00"), "USD") == Decimal("2.00")


def test_convert_to_ngn_is_a_noop_for_ngn():
    assert convert_to_ngn(Decimal("1234.56"), "NGN") == Decimal("1234.56")


@patch("apps.core.currency.get_exchange_rates")
def test_missing_rate_raises(rates):
    rates.return_value = {"USD": 1.0}
    with pytest.raises(CurrencyRateUnavailable):
        convert_to_ngn(Decimal("10.00"), "XYZ")
```

Run `python -m pytest tests/test_currency.py -q` and confirm the import fails.

### Step 1.2 — Add the helpers

Append to `apps/core/currency.py` (keep `convert_currency` unchanged; document it as display-only):

```python
class CurrencyRateUnavailable(Exception):
    """Raised when a rate needed for a real money movement is missing."""


def money(value) -> Decimal:
    """Quantise to two decimal places with ROUND_HALF_UP. Never returns a float."""
    from decimal import ROUND_HALF_UP

    return Decimal(str(value or 0)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def _usd_rate(currency: str) -> Decimal:
    currency = (currency or "USD").upper().strip()
    if currency == "USD":
        return Decimal("1")
    rates = get_exchange_rates() or {}
    rate = rates.get(currency)
    if rate in (None, 0):
        raise CurrencyRateUnavailable(
            f"No exchange rate available for {currency}."
        )
    return Decimal(str(rate))


def convert_to_ngn(amount, source_currency: str) -> Decimal:
    """
    Convert a real money amount to NGN once, returning Decimal.

    Display code keeps using convert_currency(); money movement uses this.
    """
    value = Decimal(str(amount or 0))
    source = (source_currency or "NGN").upper().strip()
    if source == "NGN":
        return money(value)
    ngn_rate = _usd_rate("NGN")
    source_rate = _usd_rate(source)
    return money(value / source_rate * ngn_rate)


def convert_from_ngn(amount, target_currency: str) -> Decimal:
    value = Decimal(str(amount or 0))
    target = (target_currency or "NGN").upper().strip()
    if target == "NGN":
        return money(value)
    return money(value / _usd_rate("NGN") * _usd_rate(target))
```

Add a module docstring note above `convert_currency`:

```python
# DISPLAY ONLY. Money movement must use convert_to_ngn/convert_from_ngn.
```

### Step 1.3 — Run

```powershell
python -m pytest tests/test_currency.py -q
```

Then the full gate.

**Commit:** `feat(core): add decimal-native currency helpers for money movement`

---

## Task 2 — Order grain, store authority, and model fields

**Why:** `Order.store` is nullable and `SET_NULL`, `Order` has no commission snapshot, and
`OrderItem` has no currency snapshot. P2 makes the store mandatory and adds the fields the money
flow needs.

**Files**

- Modify: `apps/commerce/models.py`
- Create: `apps/commerce/management/commands/backfill_order_stores.py`
- Migration: `apps/commerce/migrations/00XX_order_p2_fields.py` (generated + data migration)
- Modify: `tests/factories.py`
- Create: `tests/test_order_model.py`

### Step 2.1 — Add the backfill command first

```python
# apps/commerce/management/commands/backfill_order_stores.py
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.commerce.models import Order


class Command(BaseCommand):
    help = "Derive Order.store from its item's listing or its seller's store."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        unresolved = []

        for order in Order.objects.filter(store__isnull=True).select_related("seller"):
            store = None
            item = order.items.select_related("listing__store").first()
            if item and item.listing and item.listing.store_id:
                store = item.listing.store
            elif getattr(order.seller, "store", None):
                store = order.seller.store

            if store is None:
                unresolved.append(order.order_number)
                continue

            self.stdout.write(
                f"{order.order_number}: store -> {store.pk} ({store.name})"
            )
            if not dry_run:
                with transaction.atomic():
                    Order.objects.filter(pk=order.pk, store__isnull=True).update(
                        store=store, seller=store.user
                    )

        if unresolved:
            self.stderr.write(
                "Unresolved orders (fix manually, then re-run): "
                + ", ".join(unresolved)
            )
        else:
            self.stdout.write(self.style.SUCCESS("All orders have a store."))
```

### Step 2.2 — Add model fields

In `apps/commerce/models.py`:

`Order.store`:

```python
    store = models.ForeignKey(
        "store.Store",
        on_delete=models.PROTECT,
        null=False,
        related_name="orders",
    )
```

Add to `Order` after `delivery_fee`:

```python
    # Commission snapshot. commission_amount is platform revenue for this order.
    commission_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00")
    )
    commission_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )

    # Lifecycle audit timestamps.
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
```

Add to `Order` after the `listing` property:

```python
    @property
    def item(self):
        """The single item of this order (P2 grain)."""
        return self.items.first()

    @property
    def purchase_type(self):
        item = self.item
        return item.purchase_type if item else None
```

Add to `OrderItem` after `unit_price`:

```python
    original_currency = models.CharField(max_length=3, default="NGN")
    original_unit_price = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    exchange_rate = models.DecimalField(
        max_digits=18,
        decimal_places=8,
        default=Decimal("1.00000000"),
        help_text="NGN per unit of original_currency at checkout",
    )
```

Add `apps/commerce/models.py` top-level import if missing: `from decimal import Decimal`.

### Step 2.3 — Generate the schema migration

```powershell
python manage.py makemigrations commerce --name order_p2_fields
```

Open the generated file and, **before** the `AlterField` that sets `store` non-null, add a
`RunPython` that refuses to continue when data is unresolved:

```python
def backfill_and_guard(apps, schema_editor):
    Order = apps.get_model("commerce", "Order")
    unresolved = []
    for order in Order.objects.filter(store__isnull=True).iterator():
        item = order.items.select_related("listing__store").first()
        store_id = None
        if item and item.listing_id:
            store_id = item.listing.store_id
        if store_id is None:
            try:
                store_id = order.seller.store_id
            except Exception:
                store_id = None
        if store_id is None:
            unresolved.append(order.order_number)
            continue
        order.store_id = store_id
        order.seller_id = order.seller_id  # unchanged; store.user is authoritative
        order.save(update_fields=["store"])

    if unresolved:
        raise RuntimeError(
            "Cannot make Order.store non-null; unresolved orders: "
            + ", ".join(unresolved)
        )


def noop(apps, schema_editor):
    pass
```

Register it in `operations` **before** `AlterField`:

```python
    migrations.RunPython(backfill_and_guard, noop),
```

Then in production run in this order:

```powershell
python manage.py backfill_order_stores --dry-run
python manage.py backfill_order_stores
python manage.py migrate
```

### Step 2.4 — Update the factories

In `tests/factories.py`, make `OrderFactory` explicit about P2 fields:

```python
    commission_rate = Decimal("5.00")
    commission_amount = Decimal("0.00")
    delivered_at = None
    completed_at = None
```

`OrderItemFactory` gains:

```python
    original_currency = "NGN"
    original_unit_price = Decimal("1000.00")
    exchange_rate = Decimal("1.00000000")
```

### Step 2.5 — Write the model tests

```python
# tests/test_order_model.py
from decimal import Decimal

import pytest

from apps.commerce.models import Order

from .factories import OrderFactory, OrderItemFactory


@pytest.mark.django_db
def test_order_has_one_item_accessor():
    order = OrderFactory()
    item = OrderItemFactory(order=order)

    assert order.item == item
    assert order.purchase_type == item.purchase_type


@pytest.mark.django_db
def test_order_store_matches_seller_store():
    order = OrderFactory()

    assert order.store is not None
    assert order.seller_id == order.store.user_id


@pytest.mark.django_db
def test_commission_snapshot_defaults_to_zero_before_payment():
    order = OrderFactory(commission_amount=Decimal("0.00"))

    assert order.commission_amount == Decimal("0.00")
```

### Step 2.6 — Run

```powershell
python -m pytest tests/test_order_model.py -q
python manage.py makemigrations --check --dry-run
```

Then the full gate.

**Commit:** `feat(commerce): make the store mandatory and snapshot order money fields`

---

## Task 3 — One cart item, one order

**Why:** `CheckoutView` groups cart items by store, so three items from one store create one order
with three items. A vendor then cannot track or ship them independently. It also derives the seller
from `listing.user`, bills an escrow fee, and converts with a float helper.

**Files**

- Modify: `apps/commerce/views.py`
- Create: `tests/test_checkout.py`

### Step 3.1 — Write the failing tests

```python
# tests/test_checkout.py
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.commerce.models import Order
from apps.listings.models import Listing

from .factories import (
    CartFactory,
    CartItemFactory,
    ListingFactory,
    StoreFactory,
    UserFactory,
)


def _cart_with(items):
    buyer = UserFactory()
    cart = CartFactory(buyer=buyer)
    for listing, quantity in items:
        CartItemFactory(
            cart=cart,
            listing=listing,
            store=listing.store,
            quantity=quantity,
            unit_price=listing.price,
        )
    return buyer, cart


def _checkout(client, cart):
    with patch("apps.commerce.views.initialize_transaction") as gateway:
        gateway.return_value = {
            "authorization_url": "https://pay.test/checkout",
            "access_code": "ac_test",
        }
        return client.post(
            "/commerce/checkout/",
            {
                "cart_item_ids": list(cart.items.values_list("id", flat=True)),
                "terms_accepted": True,
            },
            format="json",
        )


@pytest.mark.django_db
def test_three_items_from_three_stores_create_three_orders(auth_client):
    listings = [
        ListingFactory(store=StoreFactory(), price=Decimal("1000.00"))
        for _ in range(3)
    ]
    buyer, cart = _cart_with([(listing, 1) for listing in listings])
    client = auth_client(buyer)

    response = _checkout(client, cart)

    assert response.status_code == 201
    orders = Order.objects.filter(buyer=buyer)
    assert orders.count() == 3
    for order in orders:
        assert order.items.count() == 1
        assert order.store_id == order.item.listing.store_id
        assert order.seller_id == order.store.user_id


@pytest.mark.django_db
def test_three_items_from_one_store_create_three_orders(auth_client):
    store = StoreFactory()
    listings = [
        ListingFactory(store=store, price=Decimal("1000.00")) for _ in range(3)
    ]
    buyer, cart = _cart_with([(listing, 1) for listing in listings])
    client = auth_client(buyer)

    response = _checkout(client, cart)

    assert response.status_code == 201
    orders = Order.objects.filter(buyer=buyer)
    assert orders.count() == 3
    assert all(order.items.count() == 1 for order in orders)


@pytest.mark.django_db
def test_buyer_total_is_subtotal_plus_delivery_with_no_fee(auth_client):
    listing = ListingFactory(price=Decimal("1000.00"), currency="NGN")
    buyer, cart = _cart_with([(listing, 3)])
    client = auth_client(buyer)

    response = _checkout(client, cart)

    order = Order.objects.get(buyer=buyer)
    assert order.subtotal == Decimal("3000.00")
    assert order.delivery_fee == Decimal("0.00")
    assert order.escrow_fee == Decimal("0.00")
    assert order.total_amount == Decimal("3000.00")
    assert Decimal(response.data["orders"][0]["total_amount"]) == Decimal("3000.00")


@pytest.mark.django_db
def test_checkout_rejects_a_listing_without_a_store(auth_client):
    listing = ListingFactory()
    buyer, cart = _cart_with([(listing, 1)])
    Listing.objects.filter(pk=listing.pk).update(store=None)
    client = auth_client(buyer)

    response = _checkout(client, cart)

    assert response.status_code == 400
    assert "store" in str(response.data).lower()
    assert Order.objects.filter(buyer=buyer).count() == 0


@pytest.mark.django_db
def test_checkout_converts_currency_once_and_snapshots_it(auth_client):
    listing = ListingFactory(
        price=Decimal("10.00"), currency="USD", store=StoreFactory()
    )
    buyer, cart = _cart_with([(listing, 1)])
    client = auth_client(buyer)

    with patch(
        "apps.commerce.views.convert_to_ngn", return_value=Decimal("15000.00")
    ):
        response = _checkout(client, cart)

    assert response.status_code == 201
    order = Order.objects.get(buyer=buyer)
    item = order.item
    assert order.subtotal == Decimal("15000.00")
    assert item.original_currency == "USD"
    assert item.original_unit_price == Decimal("10.00")
    assert item.unit_price == Decimal("15000.00")
    assert item.exchange_rate == Decimal("1500.00000000")


@pytest.mark.django_db
def test_paystack_failure_keeps_the_cart(auth_client):
    listing = ListingFactory(price=Decimal("1000.00"))
    buyer, cart = _cart_with([(listing, 1)])
    client = auth_client(buyer)

    with patch("apps.commerce.views.initialize_transaction", return_value=None):
        response = _checkout(client, cart)

    assert response.status_code == 502
    assert cart.items.count() == 1
    order = Order.objects.get(buyer=buyer)
    assert order.status == Order.Status.PENDING_PAYMENT
    assert order.checkout_session.payment.status == "failed"
```

### Step 3.2 — Replace `CheckoutView`

Replace the whole class (and keep the existing imports for `uuid`, `Decimal`, `timezone`,
`transaction`, `Payment`, `OrderActivity`, `CheckoutSession`, `OrderItem`):

```python
class CheckoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = CheckoutSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        cart_items = list(
            serializer.validated_data["cart_items"].select_related(
                "listing__store", "delivery_detail", "quote_request"
            )
        )

        missing = [
            item.listing.title
            for item in cart_items
            if item.listing.store_id is None
        ]
        if missing:
            return Response(
                {
                    "error": (
                        "These listings have no store and cannot be checked "
                        f"out: {', '.join(missing)}."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        priced = []
        grand_total = Decimal("0.00")
        for item in cart_items:
            currency = (item.listing.currency or "NGN").upper()
            try:
                subtotal = convert_to_ngn(item.subtotal, currency)
                unit_price_ngn = convert_to_ngn(item.unit_price, currency)
            except CurrencyRateUnavailable as exc:
                return Response(
                    {"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST
                )

            original_unit = Decimal(str(item.unit_price or 0))
            if original_unit > 0:
                exchange_rate = (unit_price_ngn / original_unit).quantize(
                    Decimal("0.00000001")
                )
            else:
                exchange_rate = Decimal("1.00000000")

            delivery_fee = Decimal("0.00")
            total = subtotal + delivery_fee
            grand_total += total
            priced.append(
                (item, subtotal, delivery_fee, total, unit_price_ngn,
                 original_unit, currency, exchange_rate)
            )

        with transaction.atomic():
            checkout_session = CheckoutSession.objects.create(
                buyer=request.user,
                total_amount=grand_total,
                currency="NGN",
            )

            orders_created = []
            for (
                item, subtotal, delivery_fee, total, unit_price_ngn,
                original_unit, currency, exchange_rate,
            ) in priced:
                store = item.listing.store
                order = Order.objects.create(
                    order_number=f"ORD-{uuid.uuid4().hex[:12].upper()}",
                    buyer=request.user,
                    seller=store.user,
                    store=store,
                    checkout_session=checkout_session,
                    currency="NGN",
                    subtotal=subtotal,
                    delivery_fee=delivery_fee,
                    escrow_fee=Decimal("0.00"),
                    total_amount=total,
                    commission_rate=store.commission_rate,
                    commission_amount=Decimal("0.00"),
                    status=Order.Status.PENDING_PAYMENT,
                    placed_at=timezone.now(),
                )

                rental_start = None
                rental_end = None
                if item.purchase_type in (
                    CartItem.PurchaseType.RENT,
                    CartItem.PurchaseType.LEASE,
                ):
                    rental_start = (
                        item.quote_request.preferred_delivery_date
                        if item.quote_request_id
                        and item.quote_request
                        and item.quote_request.preferred_delivery_date
                        else timezone.now().date()
                    )
                    if item.duration_days:
                        rental_end = rental_start + timedelta(
                            days=item.duration_days
                        )

                OrderItem.objects.create(
                    order=order,
                    listing=item.listing,
                    quote_request=item.quote_request,
                    purchase_type=PURCHASE_TYPE_MAP[item.purchase_type],
                    quantity=item.quantity,
                    unit_price=unit_price_ngn,
                    original_currency=currency,
                    original_unit_price=original_unit,
                    exchange_rate=exchange_rate,
                    delivery_detail=item.delivery_detail,
                    duration_days=item.duration_days,
                    rental_start_date=rental_start,
                    rental_end_date=rental_end,
                )

                OrderActivity.objects.create(
                    order=order,
                    event_type=OrderActivity.EventType.ORDER_PLACED,
                    message="Order placed successfully.",
                )

                transaction.on_commit(
                    lambda order=order: notify_order_placed(order)
                )
                track_order_placed(request.user, order)
                orders_created.append(order)

            payment = Payment.objects.create(
                checkout_session=checkout_session,
                buyer=request.user,
                amount=grand_total,
                currency="NGN",
                reference=f"PAY-{uuid.uuid4().hex[:16].upper()}",
                status=Payment.Status.PENDING,
            )

        try:
            paystack_data = initialize_transaction(
                email=request.user.email,
                amount_kobo=int(grand_total * 100),
                reference=payment.reference,
                metadata={"checkout_session_id": checkout_session.id},
                callback_url=settings.PAYSTACK_CALLBACK_URL,
            )
            if not paystack_data:
                raise ValueError("Failed to initialize payment gateway")
        except Exception as exc:
            logger.exception("Checkout payment initialisation failed: %s", exc)
            payment.status = Payment.Status.FAILED
            payment.gateway_response = {"error": str(exc)}
            payment.save(update_fields=["status", "gateway_response"])
            return Response(
                {
                    "error": "Payment gateway unavailable. Your cart is intact.",
                    "payment_id": payment.id,
                    "retry_url": (
                        f"/commerce/checkout/session/{checkout_session.id}/retry/"
                    ),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        payment.authorization_url = paystack_data.get("authorization_url", "")
        payment.paystack_access_code = paystack_data.get("access_code", "")
        payment.gateway_response = paystack_data
        payment.save(
            update_fields=[
                "authorization_url",
                "paystack_access_code",
                "gateway_response",
            ]
        )
        cart_items_qs = CartItem.objects.filter(
            pk__in=[item.pk for item in cart_items]
        )
        cart_items_qs.delete()

        return Response(
            {
                "message": f"{len(orders_created)} order(s) created.",
                "orders": [
                    {
                        "order_id": o.id,
                        "order_number": o.order_number,
                        "total_amount": str(o.total_amount),
                    }
                    for o in orders_created
                ],
                "payments": [
                    {
                        "payment_id": payment.id,
                        "authorization_url": payment.authorization_url,
                    }
                ],
            },
            status=status.HTTP_201_CREATED,
        )
```

Imports to add at the top of `views.py`:

```python
from apps.core.currency import CurrencyRateUnavailable, convert_to_ngn
from apps.commerce.models import CartItem
```

`logger` must exist at module level:

```python
logger = logging.getLogger(__name__)
```

Note: `transaction.on_commit` inside `transaction.atomic()` outside tests runs after commit; in
`pytest-django` the outer test transaction delays it, which is fine because the tests assert
database rows, not notifications. Do not assert notification delivery in checkout tests.

### Step 3.3 — Run

```powershell
python -m pytest tests/test_checkout.py -q
```

Then the full gate.

**Commit:** `feat(commerce): create one order per cart item at checkout`

---

## Task 4 — Commission snapshot and platform revenue

**Why:** `finalize_payment` only flips the status. Nothing writes `Order.commission_amount`, so
platform revenue cannot be computed from orders, and `accrue_earning` reads
`order.store.commission_rate` live — a later rate change would rewrite history.

**Files**

- Modify: `apps/commerce/services/payments.py`
- Modify: `apps/financials/services.py`
- Create: `tests/test_commission.py`

### Step 4.1 — Write the failing tests

```python
# tests/test_commission.py
from decimal import Decimal

import pytest

from apps.commerce.models import Order
from apps.commerce.services.payments import finalize_payment
from apps.financials.models import VendorEarning
from apps.financials.services import accrue_earning

from .factories import OrderFactory, OrderItemFactory, PaymentFactory


def _paid_order(rate=Decimal("5.00"), subtotal=Decimal("200000.00"),
                delivery=Decimal("5000.00")):
    order = OrderFactory(
        status=Order.Status.PENDING_PAYMENT,
        subtotal=subtotal,
        delivery_fee=delivery,
        total_amount=subtotal + delivery,
        escrow_fee=Decimal("0.00"),
    )
    order.store.commission_rate = rate
    order.store.save(update_fields=["commission_rate"])
    OrderItemFactory(order=order, unit_price=subtotal, quantity=1)
    payment = PaymentFactory(
        checkout_session=order.checkout_session,
        buyer=order.buyer,
        amount=order.total_amount,
        status="pending",
    )
    return order, payment


@pytest.mark.django_db
def test_finalize_payment_snapshots_commission():
    order, payment = _paid_order()
    finalize_payment(payment, {"amount": int(payment.amount * 100)})

    order.refresh_from_db()
    assert order.status == Order.Status.PAID
    assert order.commission_rate == Decimal("5.00")
    assert order.commission_amount == Decimal("10000.00")

    earning = VendorEarning.objects.get(order=order)
    assert earning.commission_amount == Decimal("10000.00")
    assert earning.gross_amount == Decimal("205000.00")
    assert earning.net_amount == Decimal("195000.00")


@pytest.mark.django_db
def test_commission_is_charged_on_goods_not_delivery():
    order, payment = _paid_order(
        subtotal=Decimal("1000.00"), delivery=Decimal("500.00")
    )
    finalize_payment(payment, {"amount": int(payment.amount * 100)})

    order.refresh_from_db()
    assert order.commission_amount == Decimal("50.00")


@pytest.mark.django_db
def test_accrue_earning_uses_the_snapshot_rate():
    order = OrderFactory(status=Order.Status.PAID, commission_rate=Decimal("10.00"))
    OrderItemFactory(order=order)
    order.store.commission_rate = Decimal("5.00")
    order.store.save(update_fields=["commission_rate"])

    earning = accrue_earning(order)

    assert earning.commission_rate == Decimal("10.00")


@pytest.mark.django_db
def test_platform_revenue_is_the_sum_of_commissions(auth_client):
    from .factories import UserFactory

    orders = []
    for _ in range(3):
        order, payment = _paid_order()
        finalize_payment(payment, {"amount": int(payment.amount * 100)})
        orders.append(order)

    admin = UserFactory(role="admin", is_staff=True, is_superuser=True)
    response = auth_client(admin).get("/admin-panel/payments/stats/")

    expected = sum(o.commission_amount for o in orders)
    assert Decimal(str(response.data["platform_revenue"]["value"])) == expected
    assert expected > Decimal("0.00")
```

Confirm the commission assertions fail before the change.

### Step 4.2 — Compute commission on payment

In `apps/commerce/services/payments.py`, replace the order loop:

```python
    checkout_session = payment.checkout_session
    if checkout_session:
        for order in checkout_session.orders.select_for_update():
            if order.status != Order.Status.PENDING_PAYMENT:
                continue

            rate = order.store.commission_rate
            order.commission_rate = rate
            order.commission_amount = money(
                (order.subtotal or Decimal("0.00")) * rate / Decimal("100")
            )
            order.status = Order.Status.PAID
            order.save(
                update_fields=[
                    "status", "commission_rate", "commission_amount"
                ]
            )

            transaction.on_commit(
                lambda order=order: notify_order_paid(order))
            OrderActivity.objects.create(
                order=order,
                event_type=OrderActivity.EventType.PAYMENT_CONFIRMED,
                message="Payment confirmed.",
            )
            accrue_earning(order)
```

Add `from decimal import Decimal` at the top.

### Step 4.3 — Make `accrue_earning` snapshot-driven

In `apps/financials/services.py`:

- remove the `VendorEarning.save()` auto-computation block from the model (Task 6 does the model
  edit; if Task 6 has not run yet, do it here and keep Task 6 focused on tranches);

- rewrite the defaults:

```python
    gross = money((order.subtotal or Decimal("0.00")) + (order.delivery_fee or Decimal("0.00")))
    rate = order.commission_rate or order.store.commission_rate
    commission = order.commission_amount or money(
        (order.subtotal or Decimal("0.00")) * rate / Decimal("100")
    )
    net = money(gross - commission)

    earning, created = VendorEarning.objects.get_or_create(
        order=order,
        defaults={
            "vendor": order.seller,
            "store": order.store,
            "listing": first_item.listing if first_item else None,
            "earning_type": type_map.get(purchase_type, VendorEarning.EarningType.BUY),
            "gross_amount": gross,
            "commission_rate": rate,
            "commission_amount": commission,
            "net_amount": net,
            "currency": order.currency,
            "status": VendorEarning.Status.PENDING,
            "first_release_at": timezone.now() + timedelta(days=7),
            "available_at": timezone.now() + timedelta(days=7),
        },
    )
```

If `first_release_at` does not exist yet, add it in Task 6 and reorder Task 6 before Task 4.
Preferred order: do Task 6's model field additions first. This plan keeps Task 4 before Task 6
only for narrative reasons; **if implementing strictly in order, add `first_release_at` in Task 4
and let Task 6 add `final_release_at` and `release_policy`.**

Also write the order's commission back when it is still zero:

```python
    if order.commission_amount in (None, Decimal("0.00")) and commission > Decimal("0.00"):
        order.commission_rate = rate
        order.commission_amount = commission
        order.save(update_fields=["commission_rate", "commission_amount"])
```

### Step 4.4 — Run

```powershell
python -m pytest tests/test_commission.py -q
```

Then the full gate.

**Commit:** `feat(financials): snapshot commission per order and report platform revenue`

---

## Task 5 — One lifecycle service

**Why:** the status machine is duplicated in `OrderTrackingUpdateView`, `OrderMarkShippedView`
and the cancel action. P2 needs a single place that validates transitions, writes activities,
sets timestamps, and triggers the final earnings release.

**Files**

- Create: `apps/commerce/services/orders.py`
- Modify: `apps/commerce/views.py`
- Modify: `apps/commerce/urls.py`
- Create: `tests/test_transitions.py`

### Step 5.1 — Write the failing tests

```python
# tests/test_transitions.py
from decimal import Decimal

import pytest

from apps.commerce.models import Order
from apps.commerce.services.orders import InvalidTransition, transition
from apps.financials.models import VendorEarning

from .factories import OrderFactory, OrderItemFactory


@pytest.mark.django_db
def test_transition_writes_activity_and_timestamp():
    order = OrderFactory(status=Order.Status.PAID)
    OrderItemFactory(order=order)

    transition(order, "order_confirmed", actor=order.seller)

    order.refresh_from_db()
    assert order.status == Order.Status.ORDER_CONFIRMED
    assert order.activities.filter(
        event_type="order_confirmed"
    ).exists()


@pytest.mark.django_db
def test_invalid_transition_raises():
    order = OrderFactory(status=Order.Status.PAID)
    OrderItemFactory(order=order)

    with pytest.raises(InvalidTransition):
        transition(order, "delivered", actor=order.seller)


@pytest.mark.django_db
def test_hire_order_cannot_be_fulfilled_before_the_hire_states():
    order = OrderFactory(status=Order.Status.DELIVERED)
    OrderItemFactory(order=order, purchase_type=Order.OrderType.HIRE)

    with pytest.raises(InvalidTransition):
        transition(order, "order_fulfilled", actor=order.seller)


@pytest.mark.django_db
def test_fulfilment_sets_completed_at_and_releases_the_final_tranche():
    order = OrderFactory(status=Order.Status.DELIVERED)
    OrderItemFactory(order=order)
    earning = VendorEarning.objects.create(
        order=order,
        vendor=order.seller,
        store=order.store,
        earning_type="buy",
        gross_amount=Decimal("1000.00"),
        commission_rate=Decimal("0.00"),
        commission_amount=Decimal("0.00"),
        net_amount=Decimal("1000.00"),
        released_amount=Decimal("500.00"),
        status=VendorEarning.Status.PARTIALLY_RELEASED,
    )

    transition(order, "order_fulfilled", actor=order.seller)

    order.refresh_from_db()
    earning.refresh_from_db()
    assert order.completed_at is not None
    assert earning.released_amount == Decimal("1000.00")
    assert earning.status == VendorEarning.Status.AVAILABLE


@pytest.mark.django_db
def test_confirm_receipt_is_buyer_only_and_completes(auth_client):
    order = OrderFactory(status=Order.Status.DELIVERED)
    OrderItemFactory(order=order)

    seller = auth_client(order.seller).post(
        f"/commerce/orders/{order.id}/confirm-receipt/", {}, format="json"
    )
    buyer = auth_client(order.buyer).post(
        f"/commerce/orders/{order.id}/confirm-receipt/", {}, format="json"
    )

    assert seller.status_code == 403
    assert buyer.status_code == 200
    order.refresh_from_db()
    assert order.status == Order.Status.FULFILLED
```

### Step 5.2 — Create the service

```python
# apps/commerce/services/orders.py
from django.db import transaction
from django.utils import timezone

from apps.commerce.models import Order, OrderActivity
from apps.financials.models import VendorEarning
from apps.financials.services import money, release_earning


class InvalidTransition(ValueError):
    pass


# event -> (from_statuses, to_status)
BASE_TRANSITIONS = {
    "order_cancelled": (
        (Order.Status.DRAFT, Order.Status.PENDING_PAYMENT),
        Order.Status.CANCELLED,
    ),
    "order_confirmed": ((Order.Status.PAID,), Order.Status.ORDER_CONFIRMED),
    "item_dispatched": (
        (Order.Status.ORDER_CONFIRMED,), Order.Status.ITEM_DISPATCHED
    ),
    "in_transit": ((Order.Status.ITEM_DISPATCHED,), Order.Status.IN_TRANSIT),
    "delivered": ((Order.Status.IN_TRANSIT,), Order.Status.DELIVERED),
    "order_fulfilled": ((Order.Status.DELIVERED,), Order.Status.FULFILLED),
    "hire_started": ((Order.Status.DELIVERED,), Order.Status.ACTIVE_HIRE),
    "hire_ended": ((Order.Status.ACTIVE_HIRE,), Order.Status.HIRE_ENDED),
    "item_returned": ((Order.Status.HIRE_ENDED,), Order.Status.ITEM_RETURNED),
}


def _transitions_for(order):
    table = dict(BASE_TRANSITIONS)
    has_rental = order.items.filter(
        purchase_type__in=[Order.OrderType.HIRE, Order.OrderType.LEASE]
    ).exists()
    if has_rental:
        table["order_fulfilled"] = (
            (Order.Status.ITEM_RETURNED,), Order.Status.FULFILLED
        )
    else:
        table.pop("hire_started", None)
        table.pop("hire_ended", None)
        table.pop("item_returned", None)
    return table


@transaction.atomic
def transition(order, event, actor=None, **payload):
    """
    The only function allowed to change Order.status.

    Raises InvalidTransition for an event the order cannot perform now.
    """
    order = Order.objects.select_for_update().get(pk=order.pk)
    table = _transitions_for(order)
    rule = table.get(event)
    if rule is None:
        raise InvalidTransition(f"Unknown event '{event}'.")

    from_statuses, to_status = rule
    if order.status not in from_statuses:
        raise InvalidTransition(
            f"Cannot '{event}' an order in status '{order.status}'."
        )

    now = timezone.now()
    update_fields = ["status"]

    if event == "item_dispatched":
        carrier = (payload.get("carrier") or "").strip()
        tracking_id = (payload.get("tracking_id") or "").strip()
        if not carrier or not tracking_id:
            raise InvalidTransition("carrier and tracking_id are required.")
        order.delivery_carrier = carrier
        order.tracking_id = tracking_id
        order.shipped_at = now
        update_fields += ["delivery_carrier", "tracking_id", "shipped_at"]

    if event == "delivered":
        order.delivered_at = now
        update_fields.append("delivered_at")

    if event == "order_fulfilled":
        order.completed_at = now
        update_fields.append("completed_at")

    if event == "order_cancelled":
        order.cancelled_at = now
        reason = payload.get("reason")
        if reason:
            order.cancellation_reason = reason
            update_fields.append("cancellation_reason")
        update_fields.append("cancelled_at")

    order.status = to_status
    order.save(update_fields=update_fields)

    OrderActivity.objects.create(
        order=order,
        event_type=event,
        message=payload.get("message") or f"Order moved to {to_status}.",
    )

    if event == "order_fulfilled":
        _release_final_tranche(order)

    return order


def _release_final_tranche(order):
    earning = VendorEarning.objects.filter(order=order).first()
    if earning is None or earning.is_disputed:
        return earning
    earning.final_release_at = timezone.now()
    earning.save(update_fields=["final_release_at"])
    remaining = money(earning.net_amount - earning.released_amount)
    if remaining > Decimal("0.00"):
        release_earning(earning, remaining)
    return earning
```

Add `from decimal import Decimal` at the top.

### Step 5.3 — Use the service in the views

- `OrderMarkShippedView.post`: replace the manual block with

```python
        try:
            transition(
                order,
                "item_dispatched",
                actor=request.user,
                carrier=request.data.get("carrier"),
                tracking_id=request.data.get("tracking_id"),
            )
        except InvalidTransition as exc:
            return Response({"error": str(exc)}, status=400)
```

- `OrderTrackingUpdateView.post`: replace the transition map and `order.status = ...` block with

```python
        try:
            order = transition(
                order, event, actor=request.user, message=request.data.get("message")
            )
        except InvalidTransition as exc:
            return Response({"error": str(exc)}, status=400)
```

Keep the existing seller/admin authorisation check and event allow-list; the service now owns
which events are valid.

- Add `confirm-receipt`:

```python
class OrderConfirmReceiptView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        order = get_object_or_404(Order, pk=pk, buyer=request.user)
        try:
            order = transition(order, "order_fulfilled", actor=request.user)
        except InvalidTransition as exc:
            return Response({"error": str(exc)}, status=400)
        return Response(
            {"message": "Receipt confirmed", "status": order.status}
        )
```

- Add the route:

```python
    path(
        "orders/<int:pk>/confirm-receipt/",
        OrderConfirmReceiptView.as_view(),
        name="order-confirm-receipt",
    ),
```

### Step 5.4 — Run

```powershell
python -m pytest tests/test_transitions.py tests/test_order_lifecycle.py -q
```

Then the full gate.

**Commit:** `feat(commerce): route every order status change through one service`

---

## Task 6 — Two-tranche earnings release

**Why:** earnings release in one lump on `available_at`. The spec requires 50% on day 7 and the
remainder on completion, with the vendor able to withdraw the first tranche meanwhile.

**Files**

- Modify: `apps/financials/models.py`
- Modify: `apps/financials/services.py`
- Modify: `apps/financials/tasks.py`
- Migration: `apps/financials/migrations/00XX_earning_tranches.py`
- Modify: `tests/factories.py`
- Create: `tests/test_earnings_release.py`

### Step 6.1 — Model changes

`VendorEarning`:

- add

```python
    class ReleasePolicy(models.TextChoices):
        SPLIT_50_50 = "split_50_50", _("50/50 tranches")
        FULL = "full", _("Release in full after the hold period")

    release_policy = models.CharField(
        max_length=20, choices=ReleasePolicy.choices,
        default=ReleasePolicy.SPLIT_50_50,
    )
    first_release_at = models.DateTimeField(null=True, blank=True, db_index=True)
    final_release_at = models.DateTimeField(null=True, blank=True)
```

- remove the `payout` FK entirely (replaced by `PayoutAllocation`).
- remove the `save()` auto-calculation; commission is always explicit now.

Migration:

```powershell
python manage.py makemigrations financials --name earning_tranches
```

Backfill existing rows in the migration:

```python
def backfill_tranches(apps, schema_editor):
    VendorEarning = apps.get_model("financials", "VendorEarning")
    for earning in VendorEarning.objects.all().iterator():
        if earning.first_release_at is None:
            earning.first_release_at = earning.available_at or earning.created_at
            earning.save(update_fields=["first_release_at"])


def noop(apps, schema_editor):
    pass
```

with `migrations.RunPython(backfill_tranches, noop)` after the `AddField` operations and before
`RemoveField("payout")`.

### Step 6.2 — Update the factory

```python
class VendorEarningFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = VendorEarning

    vendor = factory.SelfAttribute("store.user")
    store = factory.SubFactory(StoreFactory)
    order = factory.SubFactory(OrderFactory)
    earning_type = VendorEarning.EarningType.BUY
    gross_amount = Decimal("1000.00")
    commission_rate = Decimal("5.00")
    commission_amount = Decimal("50.00")
    net_amount = Decimal("950.00")
    currency = "NGN"
    status = VendorEarning.Status.PENDING
    release_policy = VendorEarning.ReleasePolicy.SPLIT_50_50
    available_at = factory.LazyFunction(timezone.now)
    first_release_at = factory.LazyFunction(timezone.now)
```

### Step 6.3 — Release schedule in `accrue_earning`

Set:

```python
            "release_policy": VendorEarning.ReleasePolicy.SPLIT_50_50,
            "first_release_at": now + timedelta(days=7),
            "final_release_at": None,
            "available_at": now + timedelta(days=7),
```

### Step 6.4 — Rewrite the task

```python
@shared_task
def release_pending_earnings_task():
    """
    Release the first tranche on day 7 and the remainder once the order completes.

    Rows are locked with skip_locked so concurrent workers cannot double-release.
    """
    from django.db import transaction
    from django.utils import timezone

    from .models import VendorEarning
    from .services import money, release_earning

    now = timezone.now()
    released = 0

    with transaction.atomic():
        candidates = (
            VendorEarning.objects.select_for_update(skip_locked=True)
            .filter(is_disputed=False)
            .filter(
                Q(status=VendorEarning.Status.PENDING,
                  first_release_at__lte=now)
                | Q(status=VendorEarning.Status.PARTIALLY_RELEASED,
                    final_release_at__lte=now)
            )
            .select_related("order", "store")
            .order_by("first_release_at")
        )

        for earning in candidates.iterator():
            if earning.order_id is None:
                logger.warning(
                    "Skipping orphan earning %s (no order)", earning.pk)
                continue

            if earning.status == VendorEarning.Status.PENDING:
                if earning.release_policy == VendorEarning.ReleasePolicy.FULL:
                    amount = money(
                        earning.net_amount - earning.released_amount)
                else:
                    target = money(earning.net_amount / 2)
                    amount = money(target - earning.released_amount)
            else:
                amount = money(earning.net_amount - earning.released_amount)

            if amount <= 0:
                continue
            release_earning(earning, amount)
            released += 1

    if released:
        logger.info("Released %d earning tranches", released)
    return released
```

Add `from django.db.models import Q` at the top.

### Step 6.5 — Tests

```python
# tests/test_earnings_release.py
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.financials.models import VendorEarning, VendorWallet
from apps.financials.tasks import release_pending_earnings_task

from .factories import OrderFactory, OrderItemFactory, VendorEarningFactory


def _earning(net=Decimal("1000.00"), **kwargs):
    order = OrderFactory()
    OrderItemFactory(order=order)
    return VendorEarningFactory(
        order=order, store=order.store, vendor=order.seller,
        net_amount=net, gross_amount=net, commission_amount=Decimal("0.00"),
        **kwargs,
    )


@pytest.mark.django_db
def test_first_tranche_releases_half_on_day_seven():
    earning = _earning(
        first_release_at=timezone.now() - timedelta(minutes=1)
    )

    release_pending_earnings_task()

    earning.refresh_from_db()
    assert earning.released_amount == Decimal("500.00")
    assert earning.status == VendorEarning.Status.PARTIALLY_RELEASED
    wallet = VendorWallet.objects.get(store=earning.store)
    assert wallet.available_balance == Decimal("500.00")
    assert wallet.pending_balance == Decimal("500.00")


@pytest.mark.django_db
def test_first_tranche_is_not_released_twice():
    earning = _earning(
        first_release_at=timezone.now() - timedelta(minutes=1)
    )
    release_pending_earnings_task()
    release_pending_earnings_task()

    earning.refresh_from_db()
    assert earning.released_amount == Decimal("500.00")


@pytest.mark.django_db
def test_second_tranche_releases_on_completion():
    earning = _earning(
        status=VendorEarning.Status.PARTIALLY_RELEASED,
        released_amount=Decimal("500.00"),
        first_release_at=timezone.now() - timedelta(days=7),
        final_release_at=timezone.now() - timedelta(minutes=1),
    )

    release_pending_earnings_task()

    earning.refresh_from_db()
    assert earning.released_amount == Decimal("1000.00")
    assert earning.status == VendorEarning.Status.AVAILABLE


@pytest.mark.django_db
def test_disputed_earning_is_frozen():
    earning = _earning(
        first_release_at=timezone.now() - timedelta(days=1),
        is_disputed=True,
    )

    release_pending_earnings_task()

    earning.refresh_from_db()
    assert earning.released_amount == Decimal("0.00")
```

### Step 6.6 — Run

```powershell
python -m pytest tests/test_earnings_release.py -q
```

Then the full gate.

**Commit:** `feat(financials): release earnings in 50/50 tranches`

---

## Task 7 — Per-store wallets and payout allocations

**Why:** `VendorEarning.payout` is a single FK, so one earning can only ever belong to one payout
and the second tranche cannot be allocated separately. `VendorWallet.store` is nullable, so a user
with two stores shares one balance. Payout requests must reserve the amount before allocating.

**Files**

- Modify: `apps/financials/models.py`
- Modify: `apps/financials/views.py`
- Migration: `apps/financials/migrations/00XX_wallet_store_and_allocation.py`
- Create: `tests/test_payouts.py`

### Step 7.1 — Model changes

`VendorWallet`:

```python
    store = models.OneToOneField(
        "store.Store",
        on_delete=models.CASCADE,
        related_name="wallet",
        null=False,
    )
```

Keep `user` for backwards-compatible reads (it is derived from `store.user` on write).

`Payout.store`:

```python
    store = models.ForeignKey(
        "store.Store",
        on_delete=models.PROTECT,
        related_name="payouts",
        null=False,
    )
```

Migration must first create a wallet for any store that lacks one and derive `user`:

```python
def backfill_wallets(apps, schema_editor):
    Store = apps.get_model("store", "Store")
    VendorWallet = apps.get_model("financials", "VendorWallet")
    for store in Store.objects.all().iterator():
        VendorWallet.objects.get_or_create(
            store=store,
            defaults={"user_id": store.user_id, "currency": "NGN"},
        )
    # Any wallet without a store cannot be mapped; refuse to hide it.
    orphans = VendorWallet.objects.filter(store__isnull=True)
    if orphans.exists():
        raise RuntimeError(
            "Wallets without a store must be reconciled: "
            + ", ".join(str(pk) for pk in orphans.values_list("pk", flat=True))
        )
```

### Step 7.2 — Reserve before allocating in the view

In `PayoutListCreateView.post`, the order must be:

1. lock the store wallet with `select_for_update()`;
2. reject if `available_balance < amount`;
3. create the `Payout(REQUESTED)`;
4. `allocate_payout(payout)` — FIFO over released earnings minus open allocations;
5. decrement `available_balance` by `amount` with `F()`.

The existing code already calls `allocate_payout`; move the `available_balance` decrement **after**
allocation so an allocation failure rolls the whole transaction back. Wrap the whole block in
`transaction.atomic()`.

### Step 7.3 — Tests

```python
# tests/test_payouts.py
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.financials.models import (
    Payout,
    PayoutAllocation,
    VendorEarning,
    VendorWallet,
)
from apps.financials.services import (
    allocate_payout,
    fail_payout,
    release_earning,
    settle_payout,
)

from .factories import OrderFactory, OrderItemFactory, PayoutFactory, VendorEarningFactory


def _earning(store, net=Decimal("1000.00")):
    order = OrderFactory(store=store, seller=store.user)
    OrderItemFactory(order=order)
    return VendorEarningFactory(
        order=order, store=store, vendor=store.user,
        gross_amount=net, commission_amount=Decimal("0.00"), net_amount=net,
    )


@pytest.mark.django_db
def test_vendor_can_withdraw_the_first_tranche_while_the_second_is_held():
    order = OrderFactory()
    OrderItemFactory(order=order)
    earning = VendorEarningFactory(
        order=order, store=order.store, vendor=order.seller,
        gross_amount=Decimal("1000.00"),
        commission_amount=Decimal("0.00"),
        net_amount=Decimal("1000.00"),
        first_release_at=timezone.now() - timedelta(days=1),
    )
    release_earning(earning, Decimal("500.00"))

    payout = PayoutFactory(
        store=earning.store, vendor=earning.store.user, amount=Decimal("500.00")
    )
    allocate_payout(payout)
    settle_payout(payout)

    earning.refresh_from_db()
    assert earning.released_amount == Decimal("500.00")
    assert earning.paid_out_amount == Decimal("500.00")
    assert earning.status == VendorEarning.Status.PARTIALLY_RELEASED
    assert payout.allocations.count() == 1


@pytest.mark.django_db
def test_a_payout_cannot_exceed_the_released_balance():
    store = OrderFactory().store
    earning = _earning(store)
    release_earning(earning, Decimal("400.00"))
    payout = PayoutFactory(store=store, vendor=store.user, amount=Decimal("500.00"))

    with pytest.raises(ValueError):
        allocate_payout(payout)


@pytest.mark.django_db
def test_failed_payout_restores_the_reserved_amount():
    order = OrderFactory()
    OrderItemFactory(order=order)
    earning = VendorEarningFactory(
        order=order, store=order.store, vendor=order.seller,
        gross_amount=Decimal("1000.00"),
        commission_amount=Decimal("0.00"), net_amount=Decimal("1000.00"),
    )
    release_earning(earning, Decimal("1000.00"))
    payout = PayoutFactory(
        store=earning.store, vendor=earning.store.user, amount=Decimal("500.00")
    )
    allocate_payout(payout)

    fail_payout(payout, "bank rejected")

    payout.refresh_from_db()
    assert payout.status == Payout.Status.FAILED
    assert payout.allocations.count() == 0
    assert VendorEarning.objects.get(pk=earning.pk).paid_out_amount == Decimal("0.00")
```

### Step 7.4 — Run

```powershell
python -m pytest tests/test_payouts.py -q
```

Then the full gate.

**Commit:** `feat(financials): allocate payouts per store and per earning tranche`

---

## Task 8 — Paid rental extensions

**Why:** P1 made `extend-rental` mutate dates for free. The spec requires a paid
`RentalExtension`; dates change only after the gateway confirms payment.

**Files**

- Modify: `apps/commerce/models.py`
- Modify: `apps/commerce/views.py`
- Modify: `apps/commerce/urls.py`
- Modify: `apps/commerce/services/payments.py`
- Modify: `apps/financials/services.py`
- Migration: `apps/commerce/migrations/00XX_rental_extension.py`
- Create: `tests/test_rental_extension.py`

### Step 8.1 — Model

```python
class RentalExtension(models.Model):
    """A payable extension of one hire/lease item."""

    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", _("Pending payment")
        PAID = "paid", _("Paid")
        CANCELLED = "cancelled", _("Cancelled")

    order_item = models.ForeignKey(
        OrderItem, on_delete=models.PROTECT, related_name="extensions")
    additional_days = models.PositiveIntegerField()
    previous_end_date = models.DateField()
    new_end_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, default="NGN")
    payment = models.OneToOneField(
        Payment, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="rental_extension",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.PENDING_PAYMENT, db_index=True,
    )
    applied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rental_extensions"
        ordering = ["-created_at"]
```

`RentalExtension` must be defined after `Payment`; either place it at the end of the file or use a
string reference and keep it before `Payment`. Simplest: append after `Payment`.

### Step 8.2 — New endpoint

```python
class OrderItemExtendRentalView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk, item_id):
        order = get_object_or_404(
            Order.objects.filter(buyer=request.user), pk=pk)
        item = get_object_or_404(
            OrderItem.objects.filter(
                pk=item_id,
                order=order,
                purchase_type__in=[
                    Order.OrderType.HIRE, Order.OrderType.LEASE
                ],
            )
        )

        if order.status not in (
            Order.Status.PAID,
            Order.Status.ORDER_CONFIRMED,
            Order.Status.ACTIVE_HIRE,
        ):
            return Response(
                {"error": "This order cannot be extended yet."}, status=400
            )

        if not item.rental_end_date:
            return Response(
                {"error": "This item has no rental end date."}, status=400
            )

        additional_days = request.data.get("duration_days")
        new_end_date = request.data.get("new_end_date")
        today = timezone.now().date()

        if additional_days:
            try:
                additional_days = int(additional_days)
            except (TypeError, ValueError):
                return Response(
                    {"error": "duration_days must be an integer"}, status=400
                )
            if additional_days <= 0:
                return Response(
                    {"error": "duration_days must be positive"}, status=400
                )
            parsed = item.rental_end_date + timedelta(days=additional_days)
        elif new_end_date:
            parsed = parse_date(new_end_date)
            if not parsed:
                return Response(
                    {"error": "Invalid date format. Use YYYY-MM-DD"},
                    status=400,
                )
            additional_days = (parsed - item.rental_end_date).days
            if additional_days <= 0:
                return Response(
                    {"error": "New end date must be after the current end date"},
                    status=400,
                )
        else:
            return Response(
                {"error": "duration_days or new_end_date is required"}, status=400
            )

        if parsed <= today:
            return Response(
                {"error": "The new end date must be in the future"}, status=400
            )

        amount = money(
            item.unit_price * item.quantity * additional_days
        )

        with transaction.atomic():
            extension = RentalExtension.objects.create(
                order_item=item,
                additional_days=additional_days,
                previous_end_date=item.rental_end_date,
                new_end_date=parsed,
                amount=amount,
            )
            payment = Payment.objects.create(
                buyer=request.user,
                amount=amount,
                currency="NGN",
                reference=f"PAY-{uuid.uuid4().hex[:16].upper()}",
                status=Payment.Status.PENDING,
            )
            extension.payment = payment
            extension.save(update_fields=["payment"])

        try:
            data = initialize_transaction(
                email=request.user.email,
                amount_kobo=int(amount * 100),
                reference=payment.reference,
                metadata={"rental_extension_id": extension.id},
                callback_url=settings.PAYSTACK_CALLBACK_URL,
            )
            if not data:
                raise ValueError("Failed to initialize payment gateway")
        except Exception as exc:
            logger.exception("Rental extension payment failed: %s", exc)
            payment.status = Payment.Status.FAILED
            payment.save(update_fields=["status"])
            extension.status = RentalExtension.Status.CANCELLED
            extension.save(update_fields=["status"])
            return Response(
                {"error": "Payment gateway unavailable."}, status=502
            )

        payment.authorization_url = data.get("authorization_url", "")
        payment.paystack_access_code = data.get("access_code", "")
        payment.gateway_response = data
        payment.save(
            update_fields=[
                "authorization_url", "paystack_access_code",
                "gateway_response",
            ]
        )

        return Response(
            {
                "message": "Complete payment to extend the rental.",
                "extension_id": extension.id,
                "amount": str(amount),
                "authorization_url": payment.authorization_url,
                "new_end_date": str(parsed),
            },
            status=201,
        )
```

Legacy endpoint behaviour (per spec §5.2):

```python
class OrderExtendRentalView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        order = get_object_or_404(Order, pk=pk, buyer=request.user)
        item = order.items.first()
        if item is None:
            return Response({"error": "Order has no item."}, status=400)
        return Response(
            {
                "error": (
                    "Rentals are extended per item and require payment. "
                    "Use the item endpoint."
                ),
                "item_id": item.id,
                "endpoint": (
                    f"/commerce/orders/{order.id}/items/{item.id}/extend-rental/"
                ),
            },
            status=400,
        )
```

Route:

```python
    path(
        "orders/<int:pk>/items/<int:item_id>/extend-rental/",
        OrderItemExtendRentalView.as_view(),
        name="order-item-extend-rental",
    ),
```

### Step 8.3 — Apply on payment

In `finalize_payment`, after the checkout-session loop:

```python
    if payment.rental_extension_id:
        from .rental import apply_rental_extension
        apply_rental_extension(payment.rental_extension)
```

Create `apps/commerce/services/rental.py`:

```python
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.financials.models import VendorEarning, VendorWallet
from apps.financials.services import money
from apps.notifications.utils import notify_rental_extended

from ..models import OrderActivity, RentalExtension


@transaction.atomic
def apply_rental_extension(extension: RentalExtension):
    """Apply a paid extension exactly once."""
    extension = RentalExtension.objects.select_for_update().get(pk=extension.pk)
    if extension.status == RentalExtension.Status.PAID:
        return extension
    if extension.status == RentalExtension.Status.CANCELLED:
        return extension

    item = extension.order_item
    order = item.order

    item.rental_end_date = extension.new_end_date
    item.duration_days = (item.duration_days or 0) + extension.additional_days
    item.save(update_fields=["rental_end_date", "duration_days"])

    order.subtotal = money((order.subtotal or Decimal("0.00")) + extension.amount)
    order.total_amount = money(
        (order.total_amount or Decimal("0.00")) + extension.amount
    )
    order.save(update_fields=["subtotal", "total_amount"])

    earning = VendorEarning.objects.select_for_update().filter(order=order).first()
    if earning is not None:
        extra_gross = money(extension.amount)
        extra_commission = money(
            extra_gross * earning.commission_rate / Decimal("100")
        )
        extra_net = money(extra_gross - extra_commission)

        earning.gross_amount = money(earning.gross_amount + extra_gross)
        earning.commission_amount = money(
            earning.commission_amount + extra_commission
        )
        earning.net_amount = money(earning.net_amount + extra_net)
        earning.first_release_at = timezone.now() + timezone.timedelta(days=7)
        if earning.status == VendorEarning.Status.AVAILABLE:
            earning.status = VendorEarning.Status.PARTIALLY_RELEASED
        earning.save(
            update_fields=[
                "gross_amount", "commission_amount", "net_amount",
                "first_release_at", "status",
            ]
        )

        wallet, _ = VendorWallet.objects.get_or_create(
            store=order.store,
            defaults={"user": order.store.user, "currency": "NGN"},
        )
        VendorWallet.objects.filter(pk=wallet.pk).update(
            pending_balance=models.F("pending_balance") + extra_net
        )

    extension.status = RentalExtension.Status.PAID
    extension.applied_at = timezone.now()
    extension.save(update_fields=["status", "applied_at"])

    OrderActivity.objects.create(
        order=order,
        event_type=OrderActivity.EventType.RENTAL_EXTENDED,
        message=f"Rental extended to {extension.new_end_date}.",
    )
    transaction.on_commit(lambda: notify_rental_extended(order))
    return extension
```

Add `from django.db import models` at the top (for `F`).

### Step 8.4 — Tests

```python
# tests/test_rental_extension.py
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.commerce.models import Order, RentalExtension
from apps.commerce.services.payments import finalize_payment

from .factories import OrderFactory, OrderItemFactory, PaymentFactory


def _hire_order(**kwargs):
    today = timezone.now().date()
    order = OrderFactory(status=Order.Status.ACTIVE_HIRE)
    item = OrderItemFactory(
        order=order,
        purchase_type=Order.OrderType.HIRE,
        unit_price=Decimal("1000.00"),
        quantity=1,
        duration_days=7,
        rental_start_date=today - timedelta(days=2),
        rental_end_date=today + timedelta(days=5),
    )
    return order, item


@pytest.mark.django_db
def test_extension_does_not_change_dates_until_payment(auth_client):
    order, item = _hire_order()
    client = auth_client(order.buyer)

    with patch("apps.commerce.views.initialize_transaction") as gateway:
        gateway.return_value = {"authorization_url": "https://pay.test/x"}
        response = client.post(
            f"/commerce/orders/{order.id}/items/{item.id}/extend-rental/",
            {"duration_days": 3},
            format="json",
        )

    assert response.status_code == 201
    item.refresh_from_db()
    extension = RentalExtension.objects.get(order_item=item)
    assert extension.status == RentalExtension.Status.PENDING_PAYMENT
    assert item.rental_end_date == extension.previous_end_date


@pytest.mark.django_db
def test_payment_applies_the_extension_once():
    order, item = _hire_order()
    previous_end = item.rental_end_date
    extension = RentalExtension.objects.create(
        order_item=item,
        additional_days=3,
        previous_end_date=previous_end,
        new_end_date=previous_end + timedelta(days=3),
        amount=Decimal("3000.00"),
    )
    payment = PaymentFactory(
        buyer=order.buyer,
        amount=Decimal("3000.00"),
        checkout_session=None,
    )
    extension.payment = payment
    extension.save(update_fields=["payment"])

    finalize_payment(payment, {"amount": 300000})
    finalize_payment(payment, {"amount": 300000})

    item.refresh_from_db()
    extension.refresh_from_db()
    order.refresh_from_db()
    assert item.rental_end_date == previous_end + timedelta(days=3)
    assert item.duration_days == 10
    assert extension.status == RentalExtension.Status.PAID
    assert order.subtotal == Decimal("13000.00")


@pytest.mark.django_db
def test_legacy_endpoint_points_at_the_item_endpoint(auth_client):
    order, item = _hire_order()

    response = auth_client(order.buyer).post(
        f"/commerce/orders/{order.id}/extend-rental/",
        {"duration_days": 3},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["item_id"] == item.id
    assert str(item.id) in response.data["endpoint"]
```

### Step 8.5 — Run

```powershell
python -m pytest tests/test_rental_extension.py -q
```

Then the full gate.

**Commit:** `feat(commerce): make rental extensions payable before dates change`

---

## Task 9 — Refund finalisation without phantom balances

**Why:** `finalize_refund` reverses the full earning even for a partial refund, and cancels every
order in the session. That leaves vendors short and buyers with cancelled orders they only partly
refunded.

**Files**

- Modify: `apps/commerce/services/refunds.py`
- Modify: `apps/financials/services.py`
- Create: `tests/test_refunds.py`

### Step 9.1 — Add proportional reversal

```python
# apps/financials/services.py
@transaction.atomic
def reverse_earning_amount(earning, amount, reason: str):
    """Reverse `amount` of net earnings, splitting pending and released parts."""
    from .models import VendorEarning, VendorWallet, WalletTransaction

    earning = VendorEarning.objects.select_for_update().get(pk=earning.pk)
    amount = money(amount)
    if amount <= ZERO or earning.status == VendorEarning.Status.REVERSED:
        return earning

    unreleased = money(earning.net_amount - earning.released_amount)
    from_pending = min(unreleased, amount)
    from_available = money(amount - from_pending)

    wallet, _ = VendorWallet.objects.select_for_update().get_or_create(
        store=earning.store,
        defaults={"user": earning.vendor, "currency": earning.currency},
    )
    if from_pending > ZERO:
        VendorWallet.objects.filter(pk=wallet.pk).update(
            pending_balance=F("pending_balance") - from_pending
        )
    if from_available > ZERO:
        VendorWallet.objects.filter(pk=wallet.pk).update(
            available_balance=F("available_balance") - from_available
        )

    earning.net_amount = money(earning.net_amount - amount)
    if earning.net_amount <= ZERO:
        earning.status = VendorEarning.Status.REVERSED
    earning.save(update_fields=["net_amount", "status"])

    WalletTransaction.objects.create(
        wallet=wallet,
        transaction_type=WalletTransaction.Type.REFUND,
        amount=-amount,
        description=reason,
        reference_id=str(earning.id),
    )
    return earning
```

### Step 9.2 — Rewrite `finalize_refund`

```python
@transaction.atomic
def finalize_refund(refund: Refund, payload: dict | None = None):
    """Apply a gateway-confirmed refund exactly once, proportionally."""
    from apps.financials.models import VendorEarning
    from apps.financials.services import money, reverse_earning_amount

    refund = Refund.objects.select_for_update().get(pk=refund.pk)
    if refund.status == Refund.Status.PROCESSED:
        return refund

    payment = Payment.objects.select_for_update().get(pk=refund.payment_id)
    refund.status = Refund.Status.PROCESSED
    refund.processed_at = timezone.now()
    if payload:
        refund.gateway_response = payload
    refund.save(update_fields=["status", "processed_at", "gateway_response"])

    full_refund = refund.amount >= payment.amount
    payment.status = (
        Payment.Status.REFUNDED
        if full_refund
        else Payment.Status.PARTIALLY_REFUNDED
    )
    payment.save(update_fields=["status"])

    ratio = (
        Decimal("1")
        if payment.amount == 0
        else (refund.amount / payment.amount)
    )

    if payment.checkout_session_id:
        for order in payment.checkout_session.orders.select_for_update():
            earning = VendorEarning.objects.filter(order=order).first()
            if earning is not None:
                reverse_earning_amount(
                    earning,
                    money(earning.net_amount * ratio),
                    f"Refund {refund.reference} for order {order.order_number}",
                )
            if full_refund:
                order.status = Order.Status.CANCELLED
                order.cancelled_at = timezone.now()
                order.cancellation_reason = refund.reason
                order.save(
                    update_fields=[
                        "status", "cancelled_at", "cancellation_reason"
                    ]
                )
                OrderActivity.objects.create(
                    order=order,
                    event_type=OrderActivity.EventType.ORDER_REFUNDED,
                    message=f"Refunded: {refund.reason}",
                )

    return refund
```

Add `from decimal import Decimal` and `from ..models import OrderActivity`.

Keep `reverse_earning` for the full-reversal cases already used elsewhere.

### Step 9.3 — Tests

```python
# tests/test_refunds.py
from decimal import Decimal

import pytest

from apps.commerce.models import Order, Payment, Refund
from apps.commerce.services.refunds import finalize_refund
from apps.financials.models import VendorEarning, VendorWallet

from .factories import OrderFactory, OrderItemFactory, PaymentFactory


def _paid_order():
    order = OrderFactory(
        status=Order.Status.PAID,
        subtotal=Decimal("1000.00"),
        total_amount=Decimal("1000.00"),
    )
    OrderItemFactory(order=order)
    payment = PaymentFactory(
        checkout_session=order.checkout_session,
        buyer=order.buyer,
        amount=Decimal("1000.00"),
        status=Payment.Status.SUCCESS,
    )
    earning = VendorEarning.objects.create(
        order=order, vendor=order.seller, store=order.store,
        earning_type="buy", gross_amount=Decimal("1000.00"),
        commission_rate=Decimal("0.00"), commission_amount=Decimal("0.00"),
        net_amount=Decimal("1000.00"),
        status=VendorEarning.Status.PARTIALLY_RELEASED,
        released_amount=Decimal("500.00"),
    )
    wallet, _ = VendorWallet.objects.get_or_create(
        store=order.store,
        defaults={"user": order.store.user, "currency": "NGN"},
    )
    wallet.pending_balance = Decimal("500.00")
    wallet.available_balance = Decimal("500.00")
    wallet.save(update_fields=["pending_balance", "available_balance"])
    return order, payment, earning, wallet


@pytest.mark.django_db
def test_full_refund_reverses_the_earning_and_zeroes_the_wallet():
    order, payment, earning, wallet = _paid_order()
    refund = Refund.objects.create(
        payment=payment, amount=Decimal("1000.00"),
        currency="NGN", reference="RF-FULL", reason="Not delivered",
    )

    finalize_refund(refund)

    order.refresh_from_db()
    earning.refresh_from_db()
    wallet.refresh_from_db()
    assert order.status == Order.Status.CANCELLED
    assert order.cancelled_at is not None
    assert earning.status == VendorEarning.Status.REVERSED
    assert wallet.pending_balance == Decimal("0.00")
    assert wallet.available_balance == Decimal("0.00")


@pytest.mark.django_db
def test_partial_refund_reverses_proportionally_and_keeps_the_order():
    order, payment, earning, wallet = _paid_order()
    refund = Refund.objects.create(
        payment=payment, amount=Decimal("250.00"),
        currency="NGN", reference="RF-PART", reason="Partial",
    )

    finalize_refund(refund)

    order.refresh_from_db()
    earning.refresh_from_db()
    wallet.refresh_from_db()
    assert order.status == Order.Status.PAID
    assert earning.net_amount == Decimal("750.00")
    assert wallet.pending_balance == Decimal("500.00")
    assert wallet.available_balance == Decimal("250.00")
    assert payment.status == Payment.Status.PARTIALLY_REFUNDED


@pytest.mark.django_db
def test_refund_is_idempotent():
    order, payment, earning, wallet = _paid_order()
    refund = Refund.objects.create(
        payment=payment, amount=Decimal("1000.00"),
        currency="NGN", reference="RF-ONCE", reason="Duplicate",
    )

    finalize_refund(refund)
    finalize_refund(refund)

    wallet.refresh_from_db()
    assert wallet.pending_balance == Decimal("0.00")
    assert wallet.available_balance == Decimal("0.00")
```

### Step 9.4 — Run

```powershell
python -m pytest tests/test_refunds.py -q
```

Then the full gate.

**Commit:** `fix(commerce): reverse refunds proportionally without phantom balances`

---

## Task 10 — Notification dispatcher, every channel

**Why:** every helper writes an in-app row and stops. Email, SMS, push, and the staff webhook do
not exist, so "notify the seller" means "write a row nobody sees".

**Files**

- Modify: `apps/notifications/models.py`
- Create: `apps/notifications/services.py`
- Create: `apps/notifications/channels.py`
- Modify: `apps/notifications/tasks.py`
- Modify: `apps/notifications/utils.py`
- Modify: `hb/settings.py`
- Migration: `apps/notifications/migrations/00XX_delivery_ledger.py`
- Create: `tests/test_notification_dispatch.py`

### Step 10.1 — Models

```python
class NotificationPreference(models.Model):
    """Per-user, per-category channel opt-in."""

    class Category(models.TextChoices):
        TRANSACTIONAL = "transactional", _("Transactional")
        MESSAGES = "messages", _("Messages")
        MARKETING = "marketing", _("Marketing")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    category = models.CharField(max_length=20, choices=Category.choices)
    in_app = models.BooleanField(default=True)
    email = models.BooleanField(default=True)
    sms = models.BooleanField(default=False)
    push = models.BooleanField(default=True)

    class Meta:
        db_table = "notification_preferences"
        unique_together = [("user", "category")]


class NotificationDelivery(models.Model):
    """One row per channel attempt for one notification."""

    class Channel(models.TextChoices):
        IN_APP = "in_app", _("In-app")
        EMAIL = "email", _("Email")
        SMS = "sms", _("SMS")
        PUSH = "push", _("Push")
        STAFF_WEBHOOK = "staff_webhook", _("Staff webhook")

    class Status(models.TextChoices):
        QUEUED = "queued", _("Queued")
        SENT = "sent", _("Sent")
        FAILED = "failed", _("Failed")
        SKIPPED = "skipped", _("Skipped (no credentials or opted out)")

    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE, related_name="deliveries",
        null=True, blank=True,
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="notification_deliveries",
    )
    event_key = models.CharField(max_length=50, db_index=True)
    channel = models.CharField(max_length=20, choices=Channel.choices)
    status = models.CharField(
        max_length=10, choices=Status.choices,
        default=Status.QUEUED, db_index=True,
    )
    provider_id = models.CharField(max_length=120, blank=True)
    error = models.TextField(blank=True)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "notification_deliveries"
        ordering = ["-created_at"]
```

`SKIPPED` is a deliberate addition to the spec's three statuses: without it, a no-op adapter
would have to lie and report `sent`.

### Step 10.2 — Channel adapters

```python
# apps/notifications/channels.py
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def send_email(delivery):
    """Send a plain-text email. Always available (locmem in tests)."""
    from django.core.mail import send_mail

    send_mail(
        subject=f"Harbour Hub — {delivery.event_key.replace('_', ' ').title()}",
        message=delivery.notification.message if delivery.notification else "",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[delivery.recipient.email],
        fail_silently=False,
    )
    return "sent", "", ""


def send_sms(delivery):
    provider = getattr(settings, "SMS_PROVIDER", "")
    if provider == "termii" and settings.TERMII_API_KEY:
        import requests

        response = requests.post(
            "https://api.ng.termii.com/api/sms/send",
            json={
                "to": getattr(delivery.recipient, "phone_number", "") or "",
                "from": settings.TERMII_SENDER_ID,
                "sms": delivery.notification.message,
                "type": "plain",
                "channel": "generic",
                "api_key": settings.TERMII_API_KEY,
            },
            timeout=15,
        )
        response.raise_for_status()
        return "sent", response.json().get("message_id", ""), ""

    if provider == "twilio" and settings.TWILIO_ACCOUNT_SID:
        from twilio.rest import Client

        client = Client(
            settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            to=getattr(delivery.recipient, "phone_number", "") or "",
            from_=settings.TWILIO_FROM_NUMBER,
            body=delivery.notification.message,
        )
        return "sent", message.sid, ""

    return "skipped", "", "SMS provider is not configured."


def send_push(delivery):
    if not settings.VAPID_PRIVATE_KEY:
        return "skipped", "", "Push is not configured."
    return "skipped", "", "No push subscription registered for this user."


def send_staff_webhook(delivery):
    if not settings.OPS_WEBHOOK_URL:
        return "skipped", "", "OPS_WEBHOOK_URL is not configured."
    import requests

    response = requests.post(
        settings.OPS_WEBHOOK_URL,
        json={
            "text": (
                f"[{delivery.event_key}] "
                f"{delivery.notification.message if delivery.notification else ''}"
            )
        },
        timeout=10,
    )
    response.raise_for_status()
    return "sent", "", ""
```

### Step 10.3 — Dispatcher

```python
# apps/notifications/services.py
import logging

from django.db import transaction

logger = logging.getLogger(__name__)

CHANNELS_BY_EVENT = {
    "order_placed": {"in_app", "email", "sms", "push"},
    "order_paid": {"in_app", "email", "sms", "push"},
    "payment_success": {"in_app", "email", "sms", "push"},
    "order_confirmed": {"in_app", "email", "push"},
    "order_shipped": {"in_app", "email", "sms", "push"},
    "order_delivered": {"in_app", "email", "push"},
    "order_completed": {"in_app", "email", "push"},
    "order_cancelled": {"in_app", "email", "sms", "push"},
    "order_refunded": {"in_app", "email", "sms", "push", "staff_webhook"},
    "rental_reminder": {"in_app", "email", "sms", "push"},
    "rental_extended": {"in_app", "email", "push"},
    "payout_processed": {"in_app", "email", "sms", "push"},
    "payout_failed": {"in_app", "email", "sms", "push", "staff_webhook"},
    "verification_approved": {"in_app", "email", "sms", "push"},
    "verification_rejected": {"in_app", "email", "sms", "push"},
    "new_review": {"in_app", "email", "push"},
    "new_message": {"in_app", "push"},
    "new_inquiry": {"in_app", "email", "push"},
    "inquiry_replied": {"in_app", "email", "push"},
    "quote_received": {"in_app", "email", "sms", "push"},
    "quote_responded": {"in_app", "email", "sms", "push"},
}
DEFAULT_CHANNELS = {"in_app", "email", "push"}
TRANSACTIONAL = set(CHANNELS_BY_EVENT)
ALWAYS_ON = {"in_app", "email"}


def channels_for(event_key):
    return CHANNELS_BY_EVENT.get(event_key, DEFAULT_CHANNELS)


def _preference_allows(user, channel, event_key):
    if channel in ALWAYS_ON and event_key in TRANSACTIONAL:
        return True
    from .models import NotificationPreference

    category = (
        NotificationPreference.Category.TRANSACTIONAL
        if event_key in TRANSACTIONAL
        else NotificationPreference.Category.MESSAGES
    )
    pref = NotificationPreference.objects.filter(
        user=user, category=category).first()
    if pref is None:
        return True
    return getattr(pref, channel, True)


def enqueue_deliveries(notification, event_key=None):
    """Create a ledger row per enabled channel and return the queued rows."""
    from .models import NotificationDelivery

    event_key = event_key or notification.notification_type
    queued = []
    for channel in sorted(channels_for(event_key)):
        if channel == "in_app":
            continue
        if not _preference_allows(notification.recipient, channel, event_key):
            queued.append(
                NotificationDelivery.objects.create(
                    notification=notification,
                    recipient=notification.recipient,
                    event_key=event_key,
                    channel=channel,
                    status=NotificationDelivery.Status.SKIPPED,
                    error="Recipient opted out.",
                )
            )
            continue

        delivery = NotificationDelivery.objects.create(
            notification=notification,
            recipient=notification.recipient,
            event_key=event_key,
            channel=channel,
        )
        queued.append(delivery)
        transaction.on_commit(
            lambda delivery_id=delivery.id: _schedule(delivery_id)
        )
    return queued


def _schedule(delivery_id):
    from .tasks import deliver_notification_task

    try:
        deliver_notification_task.delay(delivery_id)
    except Exception as exc:  # broker unavailable must not break the request
        logger.warning("Could not queue notification %s: %s", delivery_id, exc)
```

`channels.py` sends, `services.py` only queues.

### Step 10.4 — Delivery task

```python
# apps/notifications/tasks.py
@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def deliver_notification_task(self, delivery_id):
    from . import channels
    from .models import NotificationDelivery

    try:
        delivery = NotificationDelivery.objects.select_related(
            "notification", "recipient").get(pk=delivery_id)
    except NotificationDelivery.DoesNotExist:
        return

    if delivery.status == NotificationDelivery.Status.SENT:
        return

    senders = {
        NotificationDelivery.Channel.EMAIL: channels.send_email,
        NotificationDelivery.Channel.SMS: channels.send_sms,
        NotificationDelivery.Channel.PUSH: channels.send_push,
        NotificationDelivery.Channel.STAFF_WEBHOOK: channels.send_staff_webhook,
    }
    sender = senders.get(delivery.channel)
    if sender is None:
        delivery.status = NotificationDelivery.Status.SKIPPED
        delivery.save(update_fields=["status"])
        return

    delivery.attempts += 1
    try:
        status, provider_id, error = sender(delivery)
        delivery.status = status
        delivery.provider_id = provider_id
        delivery.error = error
        delivery.save(
            update_fields=[
                "status", "provider_id", "error", "attempts", "updated_at"
            ]
        )
    except Exception as exc:
        logger.exception(
            "Notification %s failed on %s", delivery_id, delivery.channel)
        delivery.status = NotificationDelivery.Status.FAILED
        delivery.error = str(exc)
        delivery.save(update_fields=["status", "error", "attempts", "updated_at"])
        raise self.retry(exc=exc)
```

`status` from the adapter is a string equal to the choice value, so assignment is valid.

### Step 10.5 — Wire `create_notification`

At the end of `create_notification` in `utils.py`, after the row is created:

```python
        from .services import enqueue_deliveries
        enqueue_deliveries(notif)
        return notif
```

Import it inside the existing `try` so a dispatcher failure never breaks the business action:

```python
    except Exception as exc:
        logger.exception("Failed to create notification: %s", exc)
        return None
```

Add `notify_rental_extended` and `notify_order_refunded` helpers if they do not exist; use the same
`create_notification` shape with types `rental_extended` and `order_refunded`.

### Step 10.6 — Settings

Add near the email block in `hb/settings.py`:

```python
# Notification channels. Every one is optional; empty means the adapter no-ops.
SMS_PROVIDER = config("SMS_PROVIDER", default="")
TERMII_API_KEY = config("TERMII_API_KEY", default="")
TERMII_SENDER_ID = config("TERMII_SENDER_ID", default="HarbourHub")
TWILIO_ACCOUNT_SID = config("TWILIO_ACCOUNT_SID", default="")
TWILIO_AUTH_TOKEN = config("TWILIO_AUTH_TOKEN", default="")
TWILIO_FROM_NUMBER = config("TWILIO_FROM_NUMBER", default="")
VAPID_PUBLIC_KEY = config("VAPID_PUBLIC_KEY", default="")
VAPID_PRIVATE_KEY = config("VAPID_PRIVATE_KEY", default="")
OPS_WEBHOOK_URL = config("OPS_WEBHOOK_URL", default="")
```

`hb/settings_test.py` sets `EMAIL_BACKEND` to locmem; confirm it does, otherwise add:

```python
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
```

### Step 10.7 — Tests

```python
# tests/test_notification_dispatch.py
import pytest
from django.core import mail

from apps.notifications.models import Notification, NotificationDelivery
from apps.notifications.utils import notify_order_paid

from .factories import OrderFactory, OrderItemFactory


@pytest.mark.django_db
def test_order_event_creates_a_delivery_per_channel():
    order = OrderFactory()
    OrderItemFactory(order=order)

    notify_order_paid(order)

    notification = Notification.objects.filter(
        recipient=order.buyer).get()
    channels = set(
        notification.deliveries.values_list("channel", flat=True)
    )
    assert {"email", "sms", "push"} <= channels
    assert "in_app" not in channels  # the row itself is the in-app channel


@pytest.mark.django_db
def test_email_is_actually_sent(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    order = OrderFactory()
    OrderItemFactory(order=order)

    notify_order_paid(order)
    for delivery in NotificationDelivery.objects.filter(channel="email"):
        from apps.notifications.tasks import deliver_notification_task
        deliver_notification_task(delivery.id)

    assert len(mail.outbox) >= 1


@pytest.mark.django_db
def test_sms_and_push_skip_without_credentials(settings):
    settings.SMS_PROVIDER = ""
    settings.VAPID_PRIVATE_KEY = ""
    order = OrderFactory()
    OrderItemFactory(order=order)

    notify_order_paid(order)

    for delivery in NotificationDelivery.objects.exclude(channel="email"):
        from apps.notifications.tasks import deliver_notification_task
        deliver_notification_task(delivery.id)
        delivery.refresh_from_db()
        assert delivery.status == NotificationDelivery.Status.SKIPPED


@pytest.mark.django_db
def test_opted_out_user_gets_a_skipped_row(settings):
    from apps.notifications.models import NotificationPreference

    order = OrderFactory()
    OrderItemFactory(order=order)
    NotificationPreference.objects.create(
        user=order.buyer,
        category=NotificationPreference.Category.TRANSACTIONAL,
        sms=False,
    )

    notify_order_paid(order)

    row = NotificationDelivery.objects.get(
        recipient=order.buyer, channel="sms")
    assert row.status == NotificationDelivery.Status.SKIPPED


@pytest.mark.django_db
def test_one_channel_failure_does_not_block_another(monkeypatch, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    order = OrderFactory()
    OrderItemFactory(order=order)

    from apps.notifications import channels
    monkeypatch.setattr(
        channels, "send_sms", lambda delivery: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    notify_order_paid(order)

    from apps.notifications.tasks import deliver_notification_task
    for delivery in NotificationDelivery.objects.all():
        try:
            deliver_notification_task(delivery.id)
        except Exception:
            pass

    assert Notification.objects.filter(recipient=order.buyer).exists()
```

Because `transaction.on_commit` is delayed inside the pytest transaction, `_schedule` may not run.
The tests call `deliver_notification_task` directly, so that is fine; keep the assertions about
rows rather than broker calls.

### Step 10.8 — Run

```powershell
python -m pytest tests/test_notification_dispatch.py -q
```

Then the full gate.

**Commit:** `feat(notifications): dispatch every event to every configured channel`

---

## Task 11 — Final verification and completion record

**Files**

- Create: `docs/superpowers/plans/P2-COMPLETE.md`
- Regenerate: `schema.yml`

### Step 11.1 — Full gate

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python -m pytest -q
python -m flake8 apps hb --select=F821 --exclude=migrations
python manage.py spectacular --file schema.yml --validate
```

Expected: `check` clean, no pending migrations, all tests green, no undefined names, 0 schema
errors. Operation-id warnings are acceptable until P3.

### Step 11.2 — Prove the exit criteria in one test file

Add `tests/test_p2_exit_criteria.py` that asserts, in one place:

1. three items from three stores → three orders, one item each;
2. three items from one store → three orders;
3. `order.total_amount == order.subtotal + order.delivery_fee` and `escrow_fee == 0`;
4. sum of `Order.commission_amount` equals the admin platform revenue;
5. first tranche releases half and the remainder releases on completion;
6. a payout settles the first tranche while the second stays pending;
7. a rental extension changes dates only after payment;
8. a full refund zeroes the store wallet and reverses the earning.

Each assertion is already covered by a task test; this file is the single executable summary.

### Step 11.3 — Write the completion record

`P2-COMPLETE.md` must contain:

- the commit for each task;
- the final pytest count;
- the exact commands and their output summary;
- deviations (the `SKIPPED` delivery status, commission on goods only, the legacy extend-rental
  endpoint returning `400`, migration ordering);
- what still needs staging: a real Paystack rental-extension payment, a real refund webhook, a
  real transfer success/failure, Termii/Twilio delivery, and a real web push.
- the P3 hand-off: N+1 sweep, indexes, root script cleanup, idempotent seeding, F401/F841.

**Commit:** `docs: record P2 completion and verification`

---

## Verification checklist (copy into the PR)

- [ ] `python manage.py check` clean
- [ ] `python manage.py makemigrations --check --dry-run` clean
- [ ] `python -m pytest -q` green
- [ ] `python -m flake8 apps hb --select=F821 --exclude=migrations` clean
- [ ] `python manage.py spectacular --file schema.yml --validate` 0 errors
- [ ] Backfill command run with `--dry-run` before migrating
- [ ] No data deleted, no migration faked, no table dropped
- [ ] Every task committed separately
