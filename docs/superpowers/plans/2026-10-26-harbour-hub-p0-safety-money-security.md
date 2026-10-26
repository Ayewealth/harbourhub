# Harbour Hub P0 — Safety Net, Money, and Security

> **For the implementing engineer:** This plan is written for a skilled Django developer who has
> never seen this repository. Follow the tasks in order. Every task ends with a runnable
> verification command and a commit. Do not skip Task 1; every later task depends on it.
>
> **Spec:** `docs/superpowers/specs/2026-10-26-harbour-hub-connectivity-design.md` (committed `da29bd7`).
> **Phase:** P0 only. P1–P3 get their own plans.
> **Rule:** never delete or reset existing data. Add → backfill → verify → constrain.

---

## Goal

Close the money and privilege holes before touching anything else:

1. A successful payment always creates exactly one `VendorEarning`.
2. A duplicate webhook or a `GET /payment/verify/` poll cannot double-credit.
3. A payout can only settle the earnings allocated to it.
4. A non-admin gets `403` on every admin endpoint; a read-only staff member cannot manage.
5. `role=super_admin` can no longer be self-assigned at registration.
6. `Listing.store` is server-derived, never client-supplied, and non-null.
7. The fake `sole_proprietorship` verification document disappears.
8. Buyer totals no longer include a platform fee.
9. Cart `rent` maps to the order `hire` enum so rental pricing survives checkout.
10. CI exists and is green.

## Scope boundaries

- **In scope:** the twelve P0 deliverables in §14 of the spec.
- **Out of scope (P1):** route 500s, analytics cache, admin payment list/stats, extend-rental
  response, ship endpoint, review CRUD, schema cleanup.
- **Out of scope (P2):** one-cart-item-one-order redesign, currency snapshots, 50/50 tranches,
  `RentalExtension` payment flow, notification dispatcher.
- **Transitional exception:** P0 introduces `PayoutAllocation`, `released_amount`,
  `paid_out_amount`, and `Refund` because P0 cannot safely settle payouts or refunds without them.
  P2 builds the full tranche flow on top of these fields.

---

## Working conventions

- Branch: `fix/p0-safety-money-security` off `main`.
- Python 3.11. Commands below assume the repo virtualenv is active.
- Local `.env` already points at PostgreSQL `harbour_hub`. Tests create `test_harbour_hub`;
  they never touch the development database.
- Every code block is complete. Do not invent surrounding code; place it where stated.
- Commit after every task. Commit messages are given.
- Run `python manage.py check` after every model edit.

---

## Task 1 — Test harness and CI

**Why:** every later task needs a test database, factories, eager Celery, and a CI gate. Without
this, "fixed" means "I looked at it".

**Files**

- Modify: `requirements-dev.txt`
- Create: `hb/settings_test.py`
- Create: `pytest.ini`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/factories.py`
- Create: `tests/test_harness.py`
- Create: `.github/workflows/ci.yml`
- Modify: `.github/workflows/deploy.yml`

### Step 1.1 — Add the test dependency

Append to `requirements-dev.txt`:

```text
factory-boy==3.3.3
pytest-cov==6.2.1
```

Install:

```powershell
pip install -r requirements-dev.txt
```

### Step 1.2 — Test settings

Create `hb/settings_test.py`:

```python
"""Settings for the automated test suite.

Import order matters: settings.py reads .env, so the test module must import it
first and then override anything that would reach a real service.
"""
import tempfile

from .settings import *  # noqa: F401,F403

DEBUG = False

# Database -------------------------------------------------------------------
# Use the same engine as production. CI supplies a PostgreSQL service; locally
# the developer's PostgreSQL server is used. The name is isolated from dev data.
DATABASES["default"]["TEST"] = {"NAME": "test_harbour_hub"}  # noqa: F405

# Celery ---------------------------------------------------------------------
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"

# Mail -----------------------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Storage --------------------------------------------------------------------
USE_S3 = False
MEDIA_ROOT = tempfile.mkdtemp(prefix="harbour-hub-test-media-")
MEDIA_URL = "/media/"

# Speed ----------------------------------------------------------------------
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# External services ----------------------------------------------------------
RATELIMIT_ENABLE = False
SENTRY_DSN = None
PAYSTACK_SECRET_KEY = "sk_test_p0_harness"

# Cache ----------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "harbour-hub-tests",
    }
}
```

> `settings.py` calls `config("REDIS_URL")` without a default. The repository `.env` supplies it.
> CI exports `REDIS_URL=redis://localhost:6379/0` so importing settings works before Celery is
> overridden.

### Step 1.3 — pytest configuration

Create `pytest.ini`:

```ini
[pytest]
DJANGO_SETTINGS_MODULE = hb.settings_test
python_files = tests.py test_*.py *_tests.py
testpaths = tests
addopts = -ra --strict-markers
```

Create `tests/__init__.py` (empty).

Create `tests/conftest.py`:

```python
import pytest
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_client():
    client = APIClient()

    def _authenticate(user):
        client.force_authenticate(user=user)
        return client

    return _authenticate
```

### Step 1.4 — Factories

Create `tests/factories.py`:

```python
from decimal import Decimal

import factory
from django.utils import timezone

from apps.accounts.models import User
from apps.categories.models import Category
from apps.commerce.models import Cart, CartItem, CheckoutSession, Order, OrderItem, Payment
from apps.financials.models import Payout, VendorEarning, VendorWallet
from apps.listings.models import Listing
from apps.store.models import Store


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    username = factory.Sequence(lambda n: f"user{n}")
    full_name = "Test User"
    role = User.Role.BUYER

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        self.set_password(extracted or "TestPass123!")
        if create:
            self.save(update_fields=["password"])


class StoreFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Store

    user = factory.SubFactory(UserFactory, role=User.Role.SELLER)
    name = factory.Sequence(lambda n: f"Store {n}")
    slug = factory.Sequence(lambda n: f"store-{n}")
    policy = "Standard store policy"
    is_active = True
    is_published = True


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category

    name = factory.Sequence(lambda n: f"Category {n}")
    slug = factory.Sequence(lambda n: f"category-{n}")
    is_active = True


class ListingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Listing

    user = factory.SelfAttribute("store.user")
    store = factory.SubFactory(StoreFactory)
    category = factory.SubFactory(CategoryFactory)
    title = factory.Sequence(lambda n: f"Listing {n}")
    description = "A test listing"
    listing_type = Listing.Type.SELL
    price = Decimal("1000.00")
    currency = "NGN"
    location = "Lagos"
    contact_name = "Test User"
    contact_email = "seller@example.com"
    status = Listing.Status.PUBLISHED


class CheckoutSessionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CheckoutSession

    buyer = factory.SubFactory(UserFactory)
    total_amount = Decimal("1000.00")
    currency = "NGN"


class OrderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Order

    order_number = factory.Sequence(lambda n: f"ORD-TEST-{n}")
    buyer = factory.SubFactory(UserFactory)
    seller = factory.SelfAttribute("store.user")
    store = factory.SubFactory(StoreFactory)
    checkout_session = factory.SubFactory(CheckoutSessionFactory)
    currency = "NGN"
    subtotal = Decimal("1000.00")
    total_amount = Decimal("1000.00")
    status = Order.Status.PENDING_PAYMENT
    placed_at = factory.LazyFunction(timezone.now)


class OrderItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OrderItem

    order = factory.SubFactory(OrderFactory)
    listing = factory.SubFactory(ListingFactory)
    purchase_type = Order.OrderType.BUY
    quantity = 1
    unit_price = Decimal("1000.00")


class PaymentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Payment

    checkout_session = factory.SubFactory(CheckoutSessionFactory)
    buyer = factory.SelfAttribute("checkout_session.buyer")
    amount = Decimal("1000.00")
    currency = "NGN"
    reference = factory.Sequence(lambda n: f"PAY-TEST-{n}")
    status = Payment.Status.PENDING


class CartFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Cart

    buyer = factory.SubFactory(UserFactory)


class CartItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CartItem

    cart = factory.SubFactory(CartFactory)
    listing = factory.SubFactory(ListingFactory)
    store = factory.SelfAttribute("listing.store")
    purchase_type = CartItem.PurchaseType.BUY
    quantity = 1
    unit_price = Decimal("1000.00")


class VendorWalletFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = VendorWallet

    user = factory.SelfAttribute("store.user")
    store = factory.SubFactory(StoreFactory)
    currency = "NGN"


class VendorEarningFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = VendorEarning

    vendor = factory.SelfAttribute("store.user")
    store = factory.SubFactory(StoreFactory)
    order = factory.SubFactory(OrderFactory)
    earning_type = VendorEarning.EarningType.BUY
    gross_amount = Decimal("1000.00")
    commission_rate = Decimal("5.00")
    currency = "NGN"
    status = VendorEarning.Status.PENDING
    available_at = factory.LazyFunction(timezone.now)


class PayoutFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Payout

    vendor = factory.SelfAttribute("store.user")
    store = factory.SubFactory(StoreFactory)
    amount = Decimal("100.00")
    currency = "NGN"
    reference = factory.Sequence(lambda n: f"PO-TEST-{n}")
    status = Payout.Status.REQUESTED
```

> If `Category` requires different mandatory fields than `name`/`slug`, read
> `apps/categories/models.py` and add them here. Do not weaken the model for tests.

### Step 1.5 — Harness smoke test

Create `tests/test_harness.py`:

```python
import pytest

from tests.factories import OrderFactory


@pytest.mark.django_db
def test_factories_create_a_consistent_order():
    order = OrderFactory()

    assert order.pk is not None
    assert order.store_id is not None
    assert order.seller_id == order.store.user_id
    assert order.currency == "NGN"


@pytest.mark.django_db
def test_celery_runs_eagerly(settings):
    assert settings.CELERY_TASK_ALWAYS_EAGER is True
```

Run:

```powershell
pytest tests/test_harness.py -q
```

Expected: `2 passed`. If PostgreSQL rejects the connection, start the local service or export a
`DATABASE_URL` that points at a test-capable role. Do not switch tests to SQLite; JSONField and
constraint behaviour differ.

### Step 1.6 — CI workflow

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: harbour_hub
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      redis:
        image: redis:7
        ports: ["6379:6379"]
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    env:
      DATABASE_URL: postgres://postgres:postgres@localhost:5432/harbour_hub
      REDIS_URL: redis://localhost:6379/0
      SECRET_KEY: ci-only-secret-key
      DEBUG: "False"
      PAYSTACK_SECRET_KEY: sk_test_ci
      PAYSTACK_PUBLIC_KEY: pk_test_ci

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install -r requirements-dev.txt
      # P0 gates on undefined names only. P3 expands this to F401/F841 after cleanup.
      - run: flake8 apps hb --select=F821 --exclude=migrations
      - run: python manage.py makemigrations --check --dry-run
      - run: python manage.py migrate --noinput
      - run: python manage.py spectacular --file /tmp/schema.yml --validate
      - run: pytest -q
```

### Step 1.7 — Gate deploys on CI and stop reseeding production

Replace `.github/workflows/deploy.yml`:

```yaml
name: Deploy to EC2

on:
  workflow_run:
    workflows: ["CI"]
    types: [completed]
    branches: [main]

jobs:
  deploy:
    if: ${{ github.event.workflow_run.conclusion == 'success' }}
    runs-on: ubuntu-latest
    steps:
      - name: Deploy via SSH
        uses: appleboy/ssh-action@029f5b4aeeeb58fdfe1410a5d17f967dacf36262 # v1.0.3
        with:
          host: 16.16.214.13
          username: ubuntu
          key: ${{ secrets.EC2_SSH_KEY }}
          script: |
            cd /var/www/harbourhub
            source venv/bin/activate
            git fetch origin main
            git reset --hard ${{ github.event.workflow_run.head_sha }}
            pip install -r requirements.txt
            python manage.py migrate --noinput
            python manage.py collectstatic --noinput
            sudo systemctl restart harbourhub-web harbourhub-worker harbourhub-beat nginx
```

`create_sample_data` is removed. Seeding is now an explicit operator action.

Run the full suite once:

```powershell
pytest -q
```

Commit:

```powershell
git add requirements-dev.txt hb/settings_test.py pytest.ini tests .github/workflows
git commit -m "test: add PostgreSQL test harness and CI gate"
```

---

## Task 2 — Registration always creates a buyer

**Why (D-05):** `UserRegistrationSerializer` accepts any `role`, including `super_admin`. That is
a one-request privilege escalation.

**Files**

- Modify: `apps/accounts/serializers.py`
- Modify: `apps/accounts/views.py` (only if `perform_create` passes role; it does not today)
- Create: `tests/test_auth.py`

### Step 2.1 — Write the failing test

Create `tests/test_auth.py`:

```python
import pytest
from rest_framework import status

from apps.accounts.models import User


@pytest.mark.django_db
def test_registration_rejects_privileged_role(api_client):
    response = api_client.post(
        "/auth/register/",
        {
            "email": "attacker@example.com",
            "username": "attacker",
            "full_name": "Attacker",
            "password": "S3curePass!23",
            "password_confirm": "S3curePass!23",
            "role": "super_admin",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert not User.objects.filter(email="attacker@example.com").exists()


@pytest.mark.django_db
def test_registration_without_role_creates_buyer(api_client):
    response = api_client.post(
        "/auth/register/",
        {
            "email": "buyer@example.com",
            "username": "buyer",
            "full_name": "Buyer",
            "password": "S3curePass!23",
            "password_confirm": "S3curePass!23",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert User.objects.get(email="buyer@example.com").role == User.Role.BUYER


@pytest.mark.django_db
def test_registration_rejects_seller_role(api_client):
    response = api_client.post(
        "/auth/register/",
        {
            "email": "seller-attempt@example.com",
            "username": "seller-attempt",
            "full_name": "Seller Attempt",
            "password": "S3curePass!23",
            "password_confirm": "S3curePass!23",
            "role": "seller",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert not User.objects.filter(email="seller-attempt@example.com").exists()


@pytest.mark.django_db
def test_become_seller_is_the_only_promotion_path(api_client, auth_client):
    user = User.objects.create_user(
        email="promote@example.com", password="S3curePass!23", full_name="Promote"
    )
    client = auth_client(user)

    response = client.post(
        "/auth/become-seller/",
        {"business_name": "Promote Ltd", "phone": "08000000000", "country": "NG"},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    user.refresh_from_db()
    assert user.role == User.Role.SELLER
```

> Confirm the become-seller route exists before relying on it:
> `Select-String -Path apps/accounts/urls.py -Pattern "become-seller"`.
> If it is not routed, drop the third test and keep the first two; role promotion is covered in P1.

Run:

```powershell
pytest tests/test_auth.py -q
```

Expected: first two fail, third either passes or errors on a missing route.

### Step 2.2 — Lock the serializer

In `apps/accounts/serializers.py`, replace the body of `UserRegistrationSerializer` with:

```python
class UserRegistrationSerializer(serializers.ModelSerializer):
    """Registration always creates a buyer. Seller promotion is a separate flow."""

    password = serializers.CharField(
        write_only=True, required=False, allow_blank=True, style={"input_type": "password"}
    )
    password_confirm = serializers.CharField(
        write_only=True, required=False, allow_blank=True, style={"input_type": "password"}
    )
    role = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = (
            "username",
            "email",
            "password",
            "password_confirm",
            "full_name",
            "role",
            "company",
            "phone",
            "location",
        )
        extra_kwargs = {
            "email": {"required": True},
            "full_name": {"required": True},
        }

    def validate_role(self, value):
        if value and value != User.Role.BUYER:
            raise serializers.ValidationError(
                "Registration always creates a buyer account. Use seller onboarding."
            )
        return User.Role.BUYER

    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")
        password_confirm = attrs.get("password_confirm")

        otp_valid = OneTimePassword.objects.filter(
            email__iexact=email,
            purpose=OneTimePassword.Purpose.REGISTRATION,
            used=True,
            expires_at__gte=timezone.now(),
        ).exists()

        if otp_valid:
            if password:
                if password != password_confirm:
                    raise serializers.ValidationError(
                        {"password_confirm": "Password confirmation doesn't match."}
                    )
                validate_password(password)
        else:
            if not password:
                raise serializers.ValidationError(
                    {"password": "Password is required if you haven't verified via OTP."}
                )
            if password != password_confirm:
                raise serializers.ValidationError(
                    {"password_confirm": "Password confirmation doesn't match."}
                )
            validate_password(password)

        return attrs

    def create(self, validated_data):
        validated_data.pop("password_confirm", None)
        validated_data.pop("role", None)
        password = validated_data.pop("password", None)
        validated_data["email"] = validated_data["email"].lower().strip()
        validated_data["role"] = User.Role.BUYER

        return User.objects.create_user(password=password or None, **validated_data)
```

If `User` is not imported in this module, add `from apps.accounts.models import User` (it almost
certainly already is; use the existing import).

### Step 2.3 — Install the token blacklist

`SIMPLE_JWT` already sets `BLACKLIST_AFTER_ROTATION = True`, but the app is not installed, so
rotation silently fails to revoke.

In `hb/settings.py`, add to `THIRD_PARTY_APPS`:

```python
    "rest_framework_simplejwt.token_blacklist",
```

`apps/accounts/serializers.py` already defines `CustomTokenObtainPairSerializer` and
`CustomTokenObtainPairView` uses it. Do not add a second serializer; only install the app.

### Step 2.4 — Run

```powershell
pytest tests/test_auth.py -q
python manage.py migrate --noinput
python manage.py check
```

Expected: all tests pass, migrations apply (blacklist tables).

Commit:

```powershell
git add apps/accounts/serializers.py hb/settings.py tests/test_auth.py apps/accounts/migrations
git commit -m "fix(auth): force buyer role at registration and enable token blacklist"
```

---

## Task 3 — Admin identity and module matrix

**Why (D-07):** `IsAdminOrSuperAdmin` ignores `AdminProfile`, and most admin views never check the
module matrix. An invited operations admin can hit payment or user endpoints.

**Files**

- Modify: `apps/admin_panel/auth.py`
- Modify: `apps/admin_panel/permissions.py`
- Modify: `apps/admin_panel/views.py`
- Modify: `apps/admin_panel/dashboard_views.py`
- Create: `tests/test_admin_permissions.py`
- Create: `apps/admin_panel/migrations/000X_backfill_admin_profiles.py` (generated number)

### Step 3.1 — Write the failing tests

Create `tests/test_admin_permissions.py`:

```python
import pytest
from rest_framework import status

from apps.admin_panel.constants import AdminModule, StaffRole
from apps.admin_panel.models import AdminProfile, RolePermission
from apps.accounts.models import User
from tests.factories import UserFactory


@pytest.fixture
def role_permissions(db):
    for role, modules in {
        StaffRole.OPERATIONS_ADMIN: {
            AdminModule.LISTINGS_MANAGEMENT: (True, True),
            AdminModule.PAYMENTS_FINANCE: (True, False),
        },
        StaffRole.READ_ONLY: {
            AdminModule.OVERVIEW_DASHBOARD: (True, True),
        },
    }.items():
        for module, (can_view, can_manage) in modules.items():
            RolePermission.objects.create(
                role=role, module=module, can_view=can_view, can_manage=can_manage
            )


@pytest.mark.django_db
def test_buyer_cannot_reach_admin_endpoint(auth_client):
    client = auth_client(UserFactory(role=User.Role.BUYER))
    assert client.get("/admin-panel/payments/").status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_active_admin_profile_can_view_but_not_manage(auth_client, role_permissions):
    staff = UserFactory(role=User.Role.BUYER)
    AdminProfile.objects.create(
        user=staff,
        staff_role=StaffRole.READ_ONLY,
        invite_status=AdminProfile.InviteStatus.ACTIVE,
    )
    client = auth_client(staff)

    assert client.get("/admin-panel/activity/").status_code == status.HTTP_200_OK
    assert client.post("/admin-panel/payments/payouts/1/mark-paid/").status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_role_admin_without_profile_is_not_staff(auth_client):
    user = UserFactory(role=User.Role.ADMIN)
    client = auth_client(user)
    assert client.get("/admin-panel/payments/").status_code == status.HTTP_403_FORBIDDEN
```

### Step 3.2 — Make super-admin short-circuit and add the staff permission class

In `apps/admin_panel/auth.py`, replace `has_admin_module_permission` with:

```python
def has_admin_module_permission(user, module: str, *, require_manage: bool = False) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    role = get_dashboard_staff_role(user)
    if role is None:
        return False
    if role == StaffRole.SUPER_ADMIN:
        return True
    try:
        rp = RolePermission.objects.get(role=role, module=module)
    except RolePermission.DoesNotExist:
        return False
    return rp.can_manage if require_manage else (rp.can_view or rp.can_manage)
```

In `apps/admin_panel/permissions.py`, replace `IsAdminOrSuperAdmin` with a compatibility alias and
add the new class:

```python
from rest_framework import permissions

from .auth import is_dashboard_staff


class IsDashboardStaff(permissions.BasePermission):
    """Accepts superusers, role=super_admin, and active AdminProfile rows."""

    def has_permission(self, request, view):
        return is_dashboard_staff(request.user)


# Kept temporarily so imports do not break while every view is migrated.
IsAdminOrSuperAdmin = IsDashboardStaff
```

### Step 3.3 — Apply the matrix to every admin view

For each class in `apps/admin_panel/views.py` and `apps/admin_panel/dashboard_views.py`, set:

```python
permission_classes = [IsDashboardStaff, HasAdminModulePermission]
admin_module = AdminModule.<MODULE>
admin_require_manage = <True for writes, False for reads>
```

Use this mapping exactly:

| Class | `admin_module` | `admin_require_manage` |
|---|---|---|
| `ReportedContentViewSet` | `SUPPORTS` | `True` |
| `VerificationAdminViewSet` | `VENDORS_ONBOARDING` | `True` |
| `AdminVendorListView` | `VENDORS_ONBOARDING` | `False` |
| `AdminVendorActionView` | `VENDORS_ONBOARDING` | `True` |
| `AdminListingListView` | `LISTINGS_MANAGEMENT` | `False` |
| `AdminListingActionView` | `LISTINGS_MANAGEMENT` | `True` |
| `AdminPaymentListView` | `PAYMENTS_FINANCE` | `False` |
| `AdminPaymentStatsView` | `PAYMENTS_FINANCE` | `False` |
| `AdminMarkPayoutPaidView` | `PAYMENTS_FINANCE` | `True` |
| `AdminReportStatsView` | `ANALYTICS` | `False` |
| `AdminAnalyticsExportView` | `ANALYTICS` | `False` |
| `AdminOrderViewSet` | `ORDERS_BOOKINGS` | `False` |
| `AdminOrderTrackingView` | `ORDERS_BOOKINGS` | `False` |
| `AdminActivityViewSet` | `OVERVIEW_DASHBOARD` | `False` |
| `AdminJobListingViewSet` | `CAREERS` | `True` |
| `AdminUserListView` | `USERS_MANAGEMENT` | `False` |
| `AdminUserActionView` | `USERS_MANAGEMENT` | `True` |
| `AdminConversationListView` | `MESSAGES_MONITORING` | `False` |
| `AdminConversationMessageHistoryView` | `MESSAGES_MONITORING` | `False` |
| `AdminGlobalSearchView` | `OVERVIEW_DASHBOARD` | `False` |
| `RolesMatrixView`, `InviteAdminView`, `DashboardAdminListView`, `DashboardAdminDetailView`, `AdminUserEditView` | `USERS_MANAGEMENT` | `True` |
| `MeDashboardPermissionsView` | `OVERVIEW_DASHBOARD` | `False` |
| `PlatformConfigView` (GET) | `OVERVIEW_DASHBOARD` | `False` |
| `PlatformConfigView` (PUT/PATCH) | `OVERVIEW_DASHBOARD` | `True` |
| `AcceptAdminInviteView` | — | public (`AllowAny`) |

`AdminGlobalSearchView` additionally filters its result groups:

```python
from .auth import has_admin_module_permission
from .constants import AdminModule

GROUPS = {
    "orders": AdminModule.ORDERS_BOOKINGS,
    "listings": AdminModule.LISTINGS_MANAGEMENT,
    "vendors": AdminModule.VENDORS_ONBOARDING,
    "users": AdminModule.USERS_MANAGEMENT,
}
```

Only query and return groups for which `has_admin_module_permission(request.user, module)` is true.

### Step 3.4 — Backfill profiles for legacy `role=admin`

Users with `role=ADMIN` have no `AdminProfile`; after this change they would lose access. Create a
data migration:

```powershell
python manage.py makemigrations admin_panel --empty --name backfill_admin_profiles
```

Edit the generated file:

```python
from django.db import migrations


def forwards(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    AdminProfile = apps.get_model("admin_panel", "AdminProfile")

    for user in User.objects.filter(role="admin"):
        AdminProfile.objects.get_or_create(
            user=user,
            defaults={
                "staff_role": "super_admin",
                "invite_status": "active",
            },
        )


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("admin_panel", "0001_initial"),
        ("accounts", "0001_initial"),
    ]
    operations = [migrations.RunPython(forwards, backwards)]
```

Replace the dependency names with the real latest migrations (`python manage.py showmigrations
admin_panel accounts`).

> `AdminProfile.user` may be a OneToOne or ForeignKey. Confirm with
> `Select-String -Path apps/admin_panel/models.py -Pattern "class AdminProfile" -Context 0,30`.
> If it is not OneToOne, `get_or_create(user=user)` still works.

### Step 3.5 — Run

```powershell
pytest tests/test_admin_permissions.py -q
python manage.py migrate --noinput
python manage.py check
```

Expected: 3 passed.

Commit:

```powershell
git add apps/admin_panel tests/test_admin_permissions.py
git commit -m "fix(admin): enforce dashboard staff identity and module matrix"
```

---

## Task 4 — `Listing.store` is server-derived and non-null

**Why (D-06):** the client can currently write `store`, listings can exist without a store, and
downstream code inner-joins on `store__is_published`, hiding or 500ing.

**Files**

- Modify: `apps/listings/models.py`
- Modify: `apps/listings/serializers.py`
- Modify: `apps/listings/views.py`
- Modify: `apps/store/models.py`
- Create: `tests/test_listings.py`
- Create: `apps/listings/migrations/000X_store_required.py` (generated)

### Step 4.1 — Write the failing tests

Create `tests/test_listings.py`:

```python
import pytest
from rest_framework import status

from apps.accounts.models import User
from apps.listings.models import Listing
from tests.factories import CategoryFactory, StoreFactory, UserFactory


@pytest.mark.django_db
def test_client_supplied_store_is_ignored(api_client, auth_client):
    seller = UserFactory(role=User.Role.SELLER)
    own_store = StoreFactory(user=seller)
    other_store = StoreFactory()
    category = CategoryFactory()
    client = auth_client(seller)

    response = client.post(
        "/listings/",
        {
            "title": "Generator",
            "description": "Diesel generator",
            "category": category.id,
            "store": other_store.id,
            "listing_type": "sell",
            "price": "5000.00",
            "currency": "NGN",
            "location": "Lagos",
            "contact_name": "Seller",
            "contact_email": "seller@example.com",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert Listing.objects.get(pk=response.data["id"]).store_id == own_store.id


@pytest.mark.django_db
def test_listing_without_store_returns_400(auth_client):
    seller = UserFactory(role=User.Role.SELLER)
    category = CategoryFactory()
    client = auth_client(seller)

    response = client.post(
        "/listings/",
        {
            "title": "No store",
            "description": "Cannot publish",
            "category": category.id,
            "listing_type": "sell",
            "price": "10.00",
            "currency": "NGN",
            "location": "Lagos",
            "contact_name": "Seller",
            "contact_email": "seller@example.com",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "store" in str(response.data).lower()


@pytest.mark.django_db
def test_model_refuses_storeless_listing():
    listing = ListingFactory.build(store=None)

    with pytest.raises(Exception):
        listing.save()
```

> `response.data` shape depends on the project exception handler. If it wraps errors, assert on
> `str(response.data)` instead. Do not change the handler for this test.

### Step 4.2 — Model and store model

In `apps/listings/models.py`:

```python
class ListingStoreRequired(ValueError):
    """Raised when a listing is persisted without a store."""
```

Change the field:

```python
    store = models.ForeignKey(
        Store,
        on_delete=models.PROTECT,
        related_name="listings",
        help_text=_("The store that the listing belongs to"),
    )
```

Add at the top of `Listing.save()`:

```python
        if not self.store_id:
            raise ListingStoreRequired(
                "A listing must belong to a store. Complete seller onboarding first."
            )
```

In `apps/store/models.py`, remove `limit_choices_to` from `Store.user`:

```python
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="store",
        help_text=_("The user who owns the store"),
    )
```

### Step 4.3 — Serializer

In `apps/listings/serializers.py`, remove `"store"` from `Meta.fields`. Add at the top of
`ListingCreateSerializer`:

```python
    store = serializers.PrimaryKeyRelatedField(read_only=True)
```

In `create`:

```python
        owner = request.user
        store = getattr(owner, "store", None)
        if store is None:
            raise serializers.ValidationError(
                {"store": "Complete seller onboarding before creating a listing."}
            )
        validated_data["user"] = owner
        validated_data["store"] = store
```

In `update`, after popping file fields:

```python
        validated_data.pop("store", None)
```

Remove the two debug `print()` calls at the `images_data`/`documents_data` branches (D-32 is P1,
but they are in the lines you are already editing; removing them is safe).

### Step 4.4 — View guards

In `apps/listings/views.py` `publish`, before changing status:

```python
        if not listing.store_id or not listing.store.is_active:
            return Response(
                {"error": "Listing cannot be published until its store is active."},
                status=status.HTTP_400_BAD_REQUEST,
            )
```

In `get_queryset`, replace every `store__is_published=True` + `store__is_active=True` pair with a
single `Q(store__is_active=True)`; the store must be active, but an unpublished store does not
hide a published listing. Keep the owner/admin branches. This is the P1 visibility fix, but it is
required here because `store` is now non-null and the old join would hide repaired data.

### Step 4.5 — Data migration: backfill stores

Generate:

```powershell
python manage.py makemigrations listings --empty --name backfill_listing_stores
```

Edit the generated file:

```python
from django.db import migrations
from django.utils.text import slugify


def forwards(apps, schema_editor):
    Listing = apps.get_model("listings", "Listing")
    Store = apps.get_model("store", "Store")

    storeless = Listing.objects.filter(store__isnull=True).select_related("user")
    for listing in storeless.iterator():
        user = listing.user
        store = Store.objects.filter(user=user).first()
        if store is None:
            base = slugify(user.company or user.full_name or user.email) or f"store-{user.pk}"
            slug = base
            counter = 1
            while Store.objects.filter(slug=slug).exists():
                slug = f"{base}-{counter}"
                counter += 1
            store = Store.objects.create(
                user=user,
                name=user.company or user.full_name or user.email,
                slug=slug,
                policy="",
                is_active=True,
                is_published=(listing.status == "published"),
                is_verified=getattr(user, "is_verified", False),
            )
        listing.store_id = store.pk
        listing.save(update_fields=["store"])


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("listings", "0001_initial"), ("store", "0001_initial")]
    operations = [migrations.RunPython(forwards, backwards)]
```

Then generate the schema migration:

```powershell
python manage.py makemigrations listings --name listing_store_required
```

It must contain `AlterField` for `store` with `null=False` and `on_delete=PROTECT`. Order the
migrations so the backfill runs before the `AlterField`. If Django orders them incorrectly, rename
the files and fix the `dependencies` list.

> On a fresh test database both migrations are no-ops for data, which is correct.

### Step 4.6 — Run

```powershell
python manage.py migrate --noinput
pytest tests/test_listings.py -q
python manage.py check
```

Expected: 3 passed.

Commit:

```powershell
git add apps/listings apps/store tests/test_listings.py
git commit -m "fix(listings): derive store server-side, backfill and require it"
```

---

## Task 5 — Verification documents

**Why (D-09, D-14):** `SellerOnboardingStep3Serializer` writes `business_type` into
`additional_info`, the admin drawer treats every `additional_info` value as a document, and the
endpoint therefore renders `https://api.harbourhubglobal.com/media/sole_proprietorship`.
`insurance_certificate` is required at the DB level but the onboarding never supplies it.

**Files**

- Modify: `apps/accounts/models.py`
- Modify: `apps/accounts/serializers.py`
- Modify: `apps/accounts/views.py`
- Create: `tests/test_verification_docs.py`
- Create: `apps/accounts/migrations/000X_verification_business_type.py` (generated)
- Create: `apps/accounts/migrations/000X_clean_verification_docs.py` (generated)

### Step 5.1 — Write the failing tests

Create `tests/test_verification_docs.py`:

```python
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status

from apps.accounts.models import User, VerificationRequest
from apps.accounts.serializers import VerificationRequestSerializer
from tests.factories import StoreFactory


def _file(name="doc.pdf", content=b"%PDF-1.4 test"):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


@pytest.mark.django_db
def test_onboarding_step_three_stores_business_type_not_a_document(auth_client):
    user = User.objects.create_user(
        email="vendor@example.com", password="S3curePass!23", full_name="Vendor"
    )
    StoreFactory(user=user)
    client = auth_client(user)

    response = client.post(
        "/auth/onboarding/step-3/",
        {
            "business_type": "sole_proprietorship",
            "government_id": _file("id.pdf"),
            "proof_of_registration": _file("registration.pdf"),
            "confirmed": True,
        },
        format="multipart",
    )

    assert response.status_code == status.HTTP_200_OK
    verification = VerificationRequest.objects.get(user=user)
    assert verification.business_type == "sole_proprietorship"
    assert verification.additional_info == ""
    assert not verification.business_license.name.endswith("sole_proprietorship")


@pytest.mark.django_db
def test_verification_serializer_never_returns_a_fake_document():
    user = User.objects.create_user(
        email="vendor2@example.com", password="S3curePass!23", full_name="Vendor"
    )
    verification = VerificationRequest.objects.create(
        user=user,
        company_name="Vendor Ltd",
        business_license=_file("license.pdf"),
        insurance_certificate=_file("insurance.pdf"),
        business_type="sole_proprietorship",
        additional_info="",
    )

    data = VerificationRequestSerializer(verification).data

    assert data["business_type"] == "sole_proprietorship"
    for field in ("business_license", "government_id", "insurance_certificate"):
        value = data.get(field)
        if value:
            assert value.startswith("http") or value.startswith("/")
```

> `VerificationViewSet` exposes `request` and `status` actions, not `retrieve`, so the read test
> exercises the serializer directly. The admin drawer uses the same serializer.

### Step 5.2 — Model

In `apps/accounts/models.py` `VerificationRequest`, change:

```python
    business_type = models.CharField(
        max_length=30,
        blank=True,
        choices=[
            ("sole_proprietorship", "Sole Proprietorship"),
            ("partnership", "Partnership"),
            ("limited_liability", "Limited Liability Company"),
            ("corporation", "Corporation"),
            ("ngo", "NGO / Non-profit"),
        ],
    )
    insurance_certificate = models.FileField(
        upload_to="verification/insurance/",
        null=True,
        blank=True,
        help_text=_("Insurance certificate"),
    )
```

Keep `additional_info` for genuine free text. Never write a choice value into it.

### Step 5.3 — Serializers

Replace `SellerOnboardingStep3Serializer.save`:

```python
    def save(self, user):
        from apps.accounts.models import VerificationRequest

        data = self.validated_data
        vr, _ = VerificationRequest.objects.update_or_create(
            user=user,
            defaults={
                "business_license": data["proof_of_registration"],
                "government_id": data["government_id"],
                "business_type": data["business_type"],
                "company_name": user.company or user.full_name or user.email,
            },
        )

        if user.role not in (User.Role.SELLER, User.Role.SERVICE_PROVIDER):
            user.role = User.Role.SELLER
            user.save(update_fields=["role"])

        return vr
```

Add validation:

```python
    def validate_government_id(self, value):
        if value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("Document must be 5 MB or smaller.")
        return value

    def validate_proof_of_registration(self, value):
        if value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("Document must be 5 MB or smaller.")
        return value
```

Add a create serializer for the legacy endpoint:

```python
class VerificationRequestCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = VerificationRequest
        fields = (
            "company_name",
            "business_type",
            "business_license",
            "government_id",
            "insurance_certificate",
            "certifications",
            "references",
            "additional_info",
        )

    def validate_business_type(self, value):
        allowed = {choice[0] for choice in VerificationRequest._meta.get_field("business_type").choices}
        if value and value not in allowed:
            raise serializers.ValidationError("Unknown business type.")
        return value
```

In `VerificationRequestSerializer._get_absolute_url`, guard against non-path values so a corrupt
legacy row can never produce `/media/sole_proprietorship`:

```python
    def _get_absolute_url(self, obj, field_name):
        file_field = getattr(obj, field_name, None)
        if not file_field or not getattr(file_field, "name", ""):
            return None
        name = file_field.name
        if not name.startswith(("verification/", "http://", "https://")):
            return None
        request = self.context.get("request")
        try:
            return request.build_absolute_uri(file_field.url) if request else file_field.url
        except Exception:
            return None
```

### Step 5.4 — Legacy endpoint

In `apps/accounts/views.py` `VerificationViewSet.request_verification`, replace the raw
`VerificationRequest.objects.create(...)` with:

```python
        serializer = VerificationRequestCreateSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        verification_request = serializer.save(user=request.user)
```

Add `user` to `VerificationRequestCreateSerializer.Meta.fields`? No. `serializer.save(user=...)`
works because `user` is not in validated_data and the model field is non-null; DRF passes it as an
extra kwarg. Ensure the serializer is imported at the top of `views.py`.

### Step 5.5 — Data migrations

Generate two empty migrations:

```powershell
python manage.py makemigrations accounts --empty --name verification_business_type
python manage.py makemigrations accounts --empty --name clean_verification_docs
```

`verification_business_type`:

```python
from django.db import migrations

BUSINESS_TYPES = {
    "sole_proprietorship",
    "partnership",
    "limited_liability",
    "corporation",
    "ngo",
}


def forwards(apps, schema_editor):
    VerificationRequest = apps.get_model("accounts", "VerificationRequest")
    for row in VerificationRequest.objects.all().iterator():
        marker = (row.additional_info or "").strip()
        if marker in BUSINESS_TYPES:
            row.business_type = marker
            row.additional_info = ""
            row.save(update_fields=["business_type", "additional_info"])


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]
    operations = [migrations.RunPython(forwards, backwards)]
```

`clean_verification_docs`:

```python
from django.db import migrations

BUSINESS_TYPES = {
    "sole_proprietorship",
    "partnership",
    "limited_liability",
    "corporation",
    "ngo",
}


def forwards(apps, schema_editor):
    VerificationRequest = apps.get_model("accounts", "VerificationRequest")
    fields = ("business_license", "government_id", "insurance_certificate")
    for row in VerificationRequest.objects.all().iterator():
        changed = []
        for field in fields:
            value = getattr(row, field).name if getattr(row, field) else ""
            if value in BUSINESS_TYPES:
                setattr(row, field, "")
                changed.append(field)
        if changed:
            row.save(update_fields=changed)


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("accounts", "0002_verification_business_type"),
    ]
    operations = [migrations.RunPython(forwards, backwards)]
```

Fix the dependency name to the actual generated file.

Also generate the schema migration for the model change:

```powershell
python manage.py makemigrations accounts --name verification_document_fields
```

### Step 5.6 — Run

```powershell
python manage.py migrate --noinput
pytest tests/test_verification_docs.py -q
python manage.py check
```

Expected: 2 passed.

Commit:

```powershell
git add apps/accounts tests/test_verification_docs.py
git commit -m "fix(verification): store business type separately and clean fake document paths"
```

---

## Task 6 — No buyer fee and correct rental purchase type

**Why (D-33, D-43):** buyers are charged `subtotal * 5%` labelled "ESCROW fee"; the platform earns
seller commission. `CartItem.PurchaseType.RENT = "rent"` is copied into
`OrderItem.purchase_type`, whose choices are `buy|hire|lease`, so rentals lose day-based pricing.

**Files**

- Modify: `apps/commerce/views.py`
- Create: `apps/commerce/services/__init__.py`
- Create: `tests/test_checkout.py`

### Step 6.1 — Write the failing test

Create `tests/test_checkout.py`:

```python
from decimal import Decimal

import pytest
from rest_framework import status

from apps.commerce.models import Order, OrderItem
from tests.factories import CartItemFactory


@pytest.fixture(autouse=True)
def fake_gateway(monkeypatch):
    monkeypatch.setattr(
        "apps.commerce.views.initialize_transaction",
        lambda **kwargs: {
            "authorization_url": "https://checkout.paystack.com/test",
            "access_code": "test-code",
        },
    )


@pytest.mark.django_db
def test_buyer_total_has_no_platform_fee(api_client, auth_client):
    item = CartItemFactory()
    client = auth_client(item.cart.buyer)

    response = client.post(
        "/commerce/checkout/",
        {"cart_item_ids": [item.id], "terms_accepted": True},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    order = Order.objects.get(pk=response.data["orders"][0]["order_id"])
    assert order.escrow_fee == Decimal("0.00")
    assert order.total_amount == order.subtotal


@pytest.mark.django_db
def test_rent_maps_to_hire(api_client, auth_client):
    item = CartItemFactory(
        purchase_type="rent",
        duration_days=3,
        unit_price=Decimal("100.00"),
    )
    client = auth_client(item.cart.buyer)

    response = client.post(
        "/commerce/checkout/",
        {"cart_item_ids": [item.id], "terms_accepted": True},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    order_item = OrderItem.objects.get(order__pk=response.data["orders"][0]["order_id"])
    assert order_item.purchase_type == Order.OrderType.HIRE
```

> The serializer field is `cart_item_ids`, not `cart_items`, and the view returns `201` with
> `orders[].order_id`. These names come from `CheckoutSerializer` and `CheckoutView`.

### Step 6.2 — Implement

In `apps/commerce/views.py` `CheckoutView`:

```python
    ESCROW_RATE = Decimal("0.00")  # buyers pay no platform fee; commission is seller-side
```

Replace every fee calculation with:

```python
            escrow_fee = Decimal("0.00")
            total = subtotal
```

(keep delivery fee if present: `total = subtotal + delivery_fee`).

Add at module level:

```python
PURCHASE_TYPE_MAP = {
    CartItem.PurchaseType.BUY: Order.OrderType.BUY,
    CartItem.PurchaseType.RENT: Order.OrderType.HIRE,
    CartItem.PurchaseType.LEASE: Order.OrderType.LEASE,
}
```

When creating `OrderItem`:

```python
                    purchase_type=PURCHASE_TYPE_MAP[item.purchase_type],
```

### Step 6.3 — Run

```powershell
pytest tests/test_checkout.py -q
python manage.py check
```

Expected: 2 passed.

Commit:

```powershell
git add apps/commerce
git commit -m "fix(checkout): remove buyer fee and map rent to hire"
```

---

## Task 7 — Earning accrual and wallet fields

**Why (D-01):** only the webhook creates earnings; `PaymentVerifyView` marks payments successful
and the webhook then early-returns, so verified payments never pay the vendor. Accrual must be one
idempotent function used by every confirmation path.

**Files**

- Modify: `apps/financials/models.py`
- Create: `apps/financials/services.py`
- Modify: `apps/financials/tasks.py`
- Create: `tests/test_earnings.py`
- Create: `apps/financials/migrations/000X_earning_release_fields.py` (generated)

### Step 7.1 — Model changes

`VendorEarning`:

```python
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        PARTIALLY_RELEASED = "partially_released", _("Partially Released")
        AVAILABLE = "available", _("Available")
        PROCESSING = "processing", _("Processing Payout")
        PAID_OUT = "paid_out", _("Paid Out")
        REVERSED = "reversed", _("Reversed")
```

Add fields after `available_at`:

```python
    released_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Amount moved from pending to available",
    )
    paid_out_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text="Amount settled in successful payouts",
    )
```

Add:

```python
    @property
    def releasable_amount(self):
        return max(self.net_amount - self.released_amount, Decimal("0.00"))

    @property
    def payable_amount(self):
        return max(self.released_amount - self.paid_out_amount, Decimal("0.00"))
```

Import `Decimal` at the top of the module (the file currently uses
`__import__('decimal').Decimal`; replace that with a normal import while you are there).

`PayoutAllocation`:

```python
class PayoutAllocation(models.Model):
    """Binds a slice of a payout to the earning it settles."""

    payout = models.ForeignKey(Payout, on_delete=models.CASCADE, related_name="allocations")
    earning = models.ForeignKey(
        VendorEarning, on_delete=models.PROTECT, related_name="payout_allocations"
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "payout_allocations"
        unique_together = [("payout", "earning")]
        ordering = ["created_at"]
```

### Step 7.2 — Service

Create `apps/financials/services.py`:

```python
import logging
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import F
from django.utils import timezone

logger = logging.getLogger(__name__)

ZERO = Decimal("0.00")


def money(value) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@transaction.atomic
def accrue_earning(order):
    """Create exactly one earning for a paid order and credit pending balance."""
    from apps.commerce.models import OrderItem
    from .models import VendorEarning, VendorWallet, WalletTransaction

    if order is None:
        return None
    if not order.store_id or not order.seller_id:
        logger.warning("Skipping earning accrual for order %s: no store or seller", order.pk)
        return None

    items = order.items.all()
    first_item = items.first()
    type_map = {
        "buy": VendorEarning.EarningType.BUY,
        "hire": VendorEarning.EarningType.RENT,
        "rent": VendorEarning.EarningType.RENT,
        "lease": VendorEarning.EarningType.LEASE,
    }
    purchase_type = first_item.purchase_type if first_item else "buy"

    earning, created = VendorEarning.objects.get_or_create(
        order=order,
        defaults={
            "vendor": order.seller,
            "store": order.store,
            "listing": first_item.listing if first_item else None,
            "earning_type": type_map.get(purchase_type, VendorEarning.EarningType.BUY),
            "gross_amount": order.subtotal or order.total_amount,
            "commission_rate": order.store.commission_rate,
            "currency": order.currency,
            "status": VendorEarning.Status.PENDING,
            "available_at": timezone.now() + timedelta(days=7),
        },
    )

    if created:
        wallet, _ = VendorWallet.objects.get_or_create(
            user=order.seller,
            store=order.store,
            defaults={"currency": order.currency},
        )
        VendorWallet.objects.filter(pk=wallet.pk).update(
            pending_balance=F("pending_balance") + earning.net_amount
        )
        WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type=WalletTransaction.Type.EARNING,
            amount=earning.net_amount,
            description=f"Pending earning for order {order.order_number}",
            reference_id=str(earning.id),
        )

    return earning


@transaction.atomic
def release_earning(earning, amount):
    """Move `amount` from pending to available. Idempotent guard on released_amount."""
    from .models import VendorEarning, VendorWallet, WalletTransaction

    earning = VendorEarning.objects.select_for_update().get(pk=earning.pk)
    amount = money(amount)

    if earning.status in (VendorEarning.Status.REVERSED, VendorEarning.Status.PAID_OUT):
        return earning
    if amount <= ZERO:
        return earning
    if earning.released_amount + amount > earning.net_amount:
        amount = earning.net_amount - earning.released_amount
        if amount <= ZERO:
            return earning

    wallet, _ = VendorWallet.objects.get_or_create(
        user=earning.vendor,
        store=earning.store,
        defaults={"currency": earning.currency},
    )
    VendorWallet.objects.filter(pk=wallet.pk).update(
        pending_balance=F("pending_balance") - amount,
        available_balance=F("available_balance") + amount,
    )

    earning.released_amount += amount
    if earning.released_amount >= earning.net_amount:
        earning.status = VendorEarning.Status.AVAILABLE
    else:
        earning.status = VendorEarning.Status.PARTIALLY_RELEASED
    earning.save(update_fields=["released_amount", "status"])

    WalletTransaction.objects.create(
        wallet=wallet,
        transaction_type=WalletTransaction.Type.EARNING,
        amount=amount,
        description=f"Released earning for order {earning.order.order_number if earning.order else earning.pk}",
        reference_id=str(earning.id),
    )
    return earning


@transaction.atomic
def reverse_earning(earning, reason: str):
    """Reverse an earning after a refund. Balances may go negative on purpose."""
    from .models import VendorEarning, VendorWallet, WalletTransaction

    earning = VendorEarning.objects.select_for_update().get(pk=earning.pk)
    if earning.status == VendorEarning.Status.REVERSED:
        return earning

    wallet, _ = VendorWallet.objects.get_or_create(
        user=earning.vendor,
        store=earning.store,
        defaults={"currency": earning.currency},
    )

    unreleased = money(earning.net_amount - earning.released_amount)
    if unreleased > ZERO:
        VendorWallet.objects.filter(pk=wallet.pk).update(
            pending_balance=F("pending_balance") - unreleased
        )
    if earning.released_amount > ZERO:
        VendorWallet.objects.filter(pk=wallet.pk).update(
            available_balance=F("available_balance") - earning.released_amount
        )

    earning.status = VendorEarning.Status.REVERSED
    earning.save(update_fields=["status"])

    WalletTransaction.objects.create(
        wallet=wallet,
        transaction_type=WalletTransaction.Type.REFUND,
        amount=-earning.net_amount,
        description=reason,
        reference_id=str(earning.id),
    )
    return earning
```

### Step 7.3 — Update the release task

Replace `release_pending_earnings_task` in `apps/financials/tasks.py` with:

```python
@shared_task
def release_pending_earnings_task():
    """Release earnings whose escrow window has elapsed."""
    from .models import VendorEarning
    from .services import release_earning
    from django.utils import timezone

    now = timezone.now()
    released = 0
    candidates = VendorEarning.objects.filter(
        status=VendorEarning.Status.PENDING,
        available_at__lte=now,
        is_disputed=False,
    ).select_related("order", "store")

    for earning in candidates.iterator():
        if earning.order_id is None:
            logger.warning("Skipping orphan earning %s (no order)", earning.pk)
            continue
        release_earning(earning, earning.net_amount)
        released += 1

    if released:
        logger.info("Released %d earnings", released)
    return released
```

### Step 7.4 — Tests

Create `tests/test_earnings.py`:

```python
from decimal import Decimal

import pytest

from apps.financials.models import VendorEarning
from apps.financials.services import accrue_earning, release_earning, reverse_earning
from tests.factories import OrderFactory, OrderItemFactory, VendorWalletFactory


@pytest.mark.django_db
def test_accrual_is_idempotent():
    order = OrderFactory()
    OrderItemFactory(order=order)
    earning = accrue_earning(order)
    again = accrue_earning(order)

    assert VendorEarning.objects.filter(order=order).count() == 1
    assert earning.pk == again.pk
    assert earning.net_amount == Decimal("950.00")


@pytest.mark.django_db
def test_release_moves_pending_to_available():
    order = OrderFactory()
    OrderItemFactory(order=order)
    earning = accrue_earning(order)
    wallet = VendorWalletFactory(user=order.seller, store=order.store)
    wallet.pending_balance = earning.net_amount
    wallet.save(update_fields=["pending_balance"])

    release_earning(earning, Decimal("475.00"))

    earning.refresh_from_db()
    wallet.refresh_from_db()
    assert earning.status == VendorEarning.Status.PARTIALLY_RELEASED
    assert earning.released_amount == Decimal("475.00")
    assert wallet.available_balance == Decimal("475.00")
    assert wallet.pending_balance == Decimal("475.00")


@pytest.mark.django_db
def test_reversal_does_not_leave_phantom_pending_balance():
    order = OrderFactory()
    OrderItemFactory(order=order)
    earning = accrue_earning(order)
    wallet = VendorWalletFactory(user=order.seller, store=order.store)
    wallet.pending_balance = earning.net_amount
    wallet.save(update_fields=["pending_balance"])

    reverse_earning(earning, "test refund")

    earning.refresh_from_db()
    wallet.refresh_from_db()
    assert earning.status == VendorEarning.Status.REVERSED
    assert wallet.pending_balance == Decimal("0.00")
```

Run:

```powershell
python manage.py makemigrations financials --name earning_release_fields
python manage.py migrate --noinput
pytest tests/test_earnings.py -q
```

Expected: 3 passed.

Commit:

```powershell
git add apps/financials tests/test_earnings.py
git commit -m "fix(financials): accrue exactly one earning per order with release tracking"
```

---

## Task 8 — `finalize_payment`, webhook ledger, read-only verify, reconciler

**Why (D-01, D-10):** three confirmation paths currently mutate state independently, and a verify
poll can mark success without crediting the vendor. Make one idempotent service the only writer.

**Files**

- Modify: `apps/commerce/models.py` (`WebhookEvent`)
- Create: `apps/commerce/services/__init__.py`
- Create: `apps/commerce/services/payments.py`
- Modify: `apps/commerce/webhooks.py`
- Modify: `apps/commerce/views.py` (`PaymentVerifyView`)
- Modify: `apps/commerce/tasks.py`
- Modify: `hb/settings.py` (beat schedule)
- Create: `tests/test_payments.py`
- Create: `apps/commerce/migrations/000X_webhook_event.py` (generated)

### Step 8.1 — `WebhookEvent`

In `apps/commerce/models.py`:

```python
class WebhookEvent(models.Model):
    """Idempotency ledger for gateway webhooks."""

    class Status(models.TextChoices):
        PROCESSED = "processed", _("Processed")
        IGNORED = "ignored", _("Ignored")
        FAILED = "failed", _("Failed")

    provider = models.CharField(max_length=30, default="paystack")
    event_type = models.CharField(max_length=80)
    gateway_event_id = models.CharField(max_length=120)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PROCESSED, db_index=True
    )
    payload = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "webhook_events"
        unique_together = [("provider", "event_type", "gateway_event_id")]
        ordering = ["-created_at"]
```

### Step 8.2 — Payment finalisation service

Create `apps/commerce/services/__init__.py` (empty) and
`apps/commerce/services/payments.py`:

```python
import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.financials.services import accrue_earning, money
from apps.notifications.utils import notify_order_paid

from ..models import Order, OrderActivity, Payment

logger = logging.getLogger(__name__)


class PaymentAmountMismatch(ValueError):
    pass


def _normalise_payload(payload: dict) -> dict:
    if isinstance(payload, dict) and "data" in payload and isinstance(payload["data"], dict):
        return payload["data"]
    return payload or {}


@transaction.atomic
def finalize_payment(payment, gateway_payload: dict):
    """The only function allowed to mark a payment successful.

    Returns True when this call performed the transition, False when the payment
    was already successful.
    """
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status == Payment.Status.SUCCESS:
        return False

    payload = _normalise_payload(gateway_payload)
    gateway_amount = payload.get("amount")
    if gateway_amount not in (None, 0, "0"):
        expected = int(money(payment.amount) * 100)
        if int(gateway_amount) != expected:
            raise PaymentAmountMismatch(
                f"Gateway amount {gateway_amount} != expected {expected} for {payment.reference}"
            )

    payment.status = Payment.Status.SUCCESS
    payment.paid_at = timezone.now()
    payment.gateway_response = gateway_payload or {}
    payment.save(update_fields=["status", "paid_at", "gateway_response"])

    checkout_session = payment.checkout_session
    if checkout_session:
        for order in checkout_session.orders.select_for_update():
            if order.status == Order.Status.PENDING_PAYMENT:
                order.status = Order.Status.PAID
                order.save(update_fields=["status"])

                transaction.on_commit(lambda order=order: notify_order_paid(order))
                OrderActivity.objects.create(
                    order=order,
                    event_type=OrderActivity.EventType.PAYMENT_CONFIRMED,
                    message="Payment confirmed. Funds held in escrow.",
                )
                accrue_earning(order)

    return True
```

> `notify_order_paid` is deferred until commit so an email/SMS failure can never roll back a
> successful payment.

### Step 8.3 — Webhook handler

Rewrite `apps/commerce/webhooks.py` `post` and `_handle_charge_success`:

```python
    def post(self, request):
        signature = request.headers.get("x-paystack-signature", "")
        body = request.body

        if not verify_paystack_signature(body, signature):
            logger.warning("Invalid Paystack webhook signature")
            return Response({"error": "Invalid signature"}, status=401)

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return Response({"error": "Invalid JSON"}, status=400)

        event = payload.get("event", "")
        data = payload.get("data", {}) or {}

        event_id = str(data.get("id") or data.get("reference") or hashlib.sha256(body).hexdigest())
        event_row, created = WebhookEvent.objects.get_or_create(
            provider="paystack",
            event_type=event,
            gateway_event_id=event_id,
            defaults={"payload": payload},
        )
        if not created:
            return Response({"status": "ok", "detail": "duplicate"})

        handler = {
            "charge.success": self._handle_charge_success,
            "charge.failed": self._handle_charge_failed,
            "transfer.success": self._handle_transfer_success,
            "transfer.failed": self._handle_transfer_failed,
            "transfer.reversed": self._handle_transfer_reversed,
            "refund.processed": self._handle_refund_processed,
            "refund.failed": self._handle_refund_failed,
        }.get(event)

        if handler is None:
            event_row.status = WebhookEvent.Status.IGNORED
            event_row.save(update_fields=["status"])
            return Response({"status": "ok"})

        try:
            handled = handler(data)
        except Exception as exc:
            logger.exception("Webhook handler failed for %s: %s", event, exc)
            event_row.status = WebhookEvent.Status.FAILED
            event_row.error = str(exc)
            event_row.save(update_fields=["status", "error"])
            return Response({"error": "handler failed"}, status=500)

        event_row.status = (
            WebhookEvent.Status.PROCESSED if handled else WebhookEvent.Status.IGNORED
        )
        event_row.save(update_fields=["status"])
        return Response({"status": "ok"})
```

`_handle_charge_success` becomes:

```python
    def _handle_charge_success(self, data: dict) -> bool:
        reference = data.get("reference")
        if not reference:
            return False
        try:
            payment = Payment.objects.get(reference=reference)
        except Payment.DoesNotExist:
            logger.warning("Webhook: Payment not found for reference %s", reference)
            return False
        return finalize_payment(payment, data)
```

`_handle_charge_failed`:

```python
    def _handle_charge_failed(self, data: dict) -> bool:
        reference = data.get("reference")
        if not reference:
            return False
        updated = Payment.objects.filter(
            reference=reference, status=Payment.Status.PENDING
        ).update(status=Payment.Status.FAILED)
        return bool(updated)
```

Remove `_create_vendor_earning` entirely. It is superseded by `accrue_earning`.

> `Transfer`/`refund` handlers are replaced in Tasks 9 and 10. Leave the existing transfer
> handlers callable for now; they will be rewritten next.

### Step 8.4 — Read-only verify

Replace `PaymentVerifyView.get`:

```python
    def get(self, request, reference):
        payment = get_object_or_404(Payment, reference=reference, buyer=request.user)

        if payment.status == Payment.Status.SUCCESS:
            return Response({"status": "success", "message": "Payment confirmed."})
        if payment.status in (Payment.Status.FAILED, Payment.Status.REFUNDED):
            return Response({"status": "failed", "message": "Payment was not completed."})

        paystack_data = verify_transaction(reference)
        if paystack_data is None:
            return Response(
                {"status": "unknown", "message": "Gateway unavailable. Try again shortly."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if paystack_data.get("status") == "success":
            return Response(
                {
                    "status": "pending_confirmation",
                    "message": "Awaiting webhook confirmation.",
                }
            )

        return Response({"status": "pending", "message": "Payment not completed."})
```

No `@transaction.atomic`, no `payment.save()`, no `order.save()`. Delete the unused
`track_payment_success`/`track_payment_failed` imports if they become unused.

### Step 8.5 — Reconciler task

In `apps/commerce/tasks.py` add:

```python
@shared_task
def reconcile_pending_payments_task():
    """Safety net for lost webhooks. Never double-credits because finalize is idempotent."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.commerce.models import Payment
    from apps.commerce.paystack import verify_transaction
    from apps.commerce.services.payments import finalize_payment

    cutoff = timezone.now() - timedelta(minutes=10)
    reconciled = 0
    candidates = Payment.objects.filter(
        status=Payment.Status.PENDING, created_at__lt=cutoff
    ).select_related("checkout_session")

    for payment in candidates.iterator():
        data = verify_transaction(payment.reference)
        if not data or data.get("status") != "success":
            continue
        finalize_payment(payment, data)
        reconciled += 1

    return reconciled
```

Add to `CELERY_BEAT_SCHEDULE`:

```python
    "reconcile-pending-payments-every-five-minutes": {
        "task": "apps.commerce.tasks.reconcile_pending_payments_task",
        "schedule": crontab(minute="*/5"),
    },
```

### Step 8.6 — Tests

Create `tests/test_payments.py`:

```python
import hashlib
import hmac
import json
from decimal import Decimal

import pytest
from django.conf import settings
from rest_framework import status

from apps.commerce.models import Payment, WebhookEvent
from apps.commerce.services.payments import finalize_payment
from apps.financials.models import VendorEarning
from tests.factories import OrderFactory, OrderItemFactory, PaymentFactory


def _signed(client, payload):
    body = json.dumps(payload).encode()
    signature = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode(), body, hashlib.sha512
    ).hexdigest()
    return client.post(
        "/commerce/payment/webhook/",
        data=body,
        content_type="application/json",
        HTTP_X_PAYSTACK_SIGNATURE=signature,
    )


@pytest.mark.django_db
def test_finalize_is_idempotent():
    order = OrderFactory()
    OrderItemFactory(order=order)
    payment = PaymentFactory(checkout_session=order.checkout_session, amount=order.total_amount)

    assert finalize_payment(payment, {"reference": payment.reference, "amount": int(payment.amount * 100)}) is True
    assert finalize_payment(payment, {"reference": payment.reference}) is False
    assert VendorEarning.objects.filter(order=order).count() == 1


@pytest.mark.django_db
def test_duplicate_webhook_is_ignored(api_client):
    order = OrderFactory()
    OrderItemFactory(order=order)
    payment = PaymentFactory(checkout_session=order.checkout_session, amount=order.total_amount)
    payload = {
        "event": "charge.success",
        "data": {
            "id": 99123,
            "reference": payment.reference,
            "amount": int(payment.amount * 100),
        },
    }

    assert _signed(api_client, payload).status_code == 200
    assert _signed(api_client, payload).status_code == 200

    assert WebhookEvent.objects.count() == 1
    assert VendorEarning.objects.filter(order=order).count() == 1


@pytest.mark.django_db
def test_bad_signature_is_rejected(api_client):
    response = api_client.post(
        "/commerce/payment/webhook/",
        data=json.dumps({"event": "charge.success", "data": {}}),
        content_type="application/json",
        HTTP_X_PAYSTACK_SIGNATURE="nope",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_verify_never_writes(api_client, auth_client, monkeypatch):
    payment = PaymentFactory()
    client = auth_client(payment.buyer)
    monkeypatch.setattr(
        "apps.commerce.views.verify_transaction",
        lambda reference: {"status": "success", "reference": reference, "amount": 0},
    )

    response = client.get(f"/commerce/payment/verify/{payment.reference}/")

    assert response.status_code == 200
    assert response.data["status"] == "pending_confirmation"
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PENDING
```

Run:

```powershell
python manage.py makemigrations commerce --name webhook_event
python manage.py migrate --noinput
pytest tests/test_payments.py -q
```

Expected: 4 passed.

Commit:

```powershell
git add apps/commerce hb/settings.py tests/test_payments.py
git commit -m "fix(payments): single idempotent finalizer, webhook ledger, read-only verify, reconciler"
```

---

## Task 9 — Payout allocations and safe settlement

**Why (D-02, D-03, D-12, D-37):** `VendorEarning.payout` is never assigned, payout filters match
zero rows, and `AdminMarkPayoutPaidView` marks every available earning paid, including earnings
from other payouts.

**Files**

- Modify: `apps/financials/views.py`
- Modify: `apps/financials/services.py`
- Modify: `apps/commerce/webhooks.py`
- Modify: `apps/admin_panel/views.py`
- Create: `tests/test_payouts.py`

### Step 9.1 — Settlement services

Append to `apps/financials/services.py`:

```python
@transaction.atomic
def allocate_payout(payout):
    """FIFO-allocate released earnings to a payout. Returns the allocated total."""
    from django.db.models import Sum

    from .models import Payout, PayoutAllocation, VendorEarning

    payout = Payout.objects.select_for_update().get(pk=payout.pk)
    remaining = money(payout.amount)
    allocated = ZERO

    earnings = (
        VendorEarning.objects.select_for_update()
        .filter(
            vendor=payout.vendor,
            store=payout.store,
            status__in=(
                VendorEarning.Status.AVAILABLE,
                VendorEarning.Status.PARTIALLY_RELEASED,
            ),
        )
        .order_by("available_at", "created_at")
    )

    for earning in earnings:
        if remaining <= ZERO:
            break
        open_allocated = (
            earning.payout_allocations.filter(
                payout__status__in=(Payout.Status.REQUESTED, Payout.Status.PROCESSING)
            ).aggregate(total=Sum("amount"))["total"]
            or ZERO
        )
        available = money(earning.released_amount - earning.paid_out_amount - open_allocated)
        if available <= ZERO:
            continue
        take = min(available, remaining)
        PayoutAllocation.objects.create(payout=payout, earning=earning, amount=take)
        remaining -= take
        allocated += take

    if remaining > ZERO:
        raise ValueError(
            f"Payout {payout.pk} is under-allocated by {remaining}; wallet balance is inconsistent."
        )

    return allocated


@transaction.atomic
def settle_payout(payout):
    """Mark a payout paid and settle only its allocations."""
    from .models import Payout, VendorEarning, VendorWallet

    payout = Payout.objects.select_for_update().get(pk=payout.pk)
    if payout.status == Payout.Status.PAID:
        return payout

    for allocation in payout.allocations.select_related("earning"):
        earning = VendorEarning.objects.select_for_update().get(pk=allocation.earning_id)
        earning.paid_out_amount = money(earning.paid_out_amount + allocation.amount)
        if earning.paid_out_amount >= earning.net_amount:
            earning.status = VendorEarning.Status.PAID_OUT
        elif earning.status == VendorEarning.Status.AVAILABLE:
            earning.status = VendorEarning.Status.PARTIALLY_RELEASED
        earning.save(update_fields=["paid_out_amount", "status"])

    wallet = VendorWallet.objects.select_for_update().get(
        user=payout.vendor, store=payout.store
    )
    wallet.total_withdrawn = money(wallet.total_withdrawn + payout.amount)
    wallet.save(update_fields=["total_withdrawn"])

    payout.status = Payout.Status.PAID
    payout.processed_at = timezone.now()
    payout.save(update_fields=["status", "processed_at"])
    return payout


@transaction.atomic
def fail_payout(payout, reason: str):
    """Reverse allocations and re-credit the reserved amount."""
    from .models import Payout, VendorEarning, VendorWallet, WalletTransaction

    payout = Payout.objects.select_for_update().get(pk=payout.pk)
    if payout.status in (Payout.Status.FAILED, Payout.Status.PAID):
        return payout

    wallet = VendorWallet.objects.select_for_update().get(
        user=payout.vendor, store=payout.store
    )
    VendorWallet.objects.filter(pk=wallet.pk).update(
        available_balance=F("available_balance") + payout.amount
    )

    for allocation in payout.allocations.select_related("earning"):
        earning = VendorEarning.objects.select_for_update().get(pk=allocation.earning_id)
        if earning.status == VendorEarning.Status.PROCESSING:
            earning.status = (
                VendorEarning.Status.AVAILABLE
                if earning.released_amount >= earning.net_amount
                else VendorEarning.Status.PARTIALLY_RELEASED
            )
            earning.save(update_fields=["status"])

    payout.allocations.all().delete()
    payout.status = Payout.Status.FAILED
    payout.failure_reason = reason
    payout.save(update_fields=["status", "failure_reason"])

    WalletTransaction.objects.create(
        wallet=wallet,
        transaction_type=WalletTransaction.Type.REFUND,
        amount=payout.amount,
        description=f"Re-credited failed payout {payout.reference}",
        reference_id=str(payout.pk),
    )
    return payout
```

### Step 9.2 — Fix payout request

Also patch `PayoutCreateSerializer.validate` in `apps/financials/serializers.py` so it looks up the
wallet for the user's store instead of assuming one wallet per user:

```python
    def validate(self, attrs):
        user = self.context["request"].user
        store = getattr(user, "store", None)
        wallet = VendorWallet.objects.filter(user=user, store=store).first()
        if wallet is None:
            raise serializers.ValidationError("Wallet not found.")
        if attrs["amount"] > wallet.available_balance:
            raise serializers.ValidationError(
                f"Insufficient balance. Available: {wallet.available_balance}"
            )
        return attrs
```

Replace `PayoutListCreateView.perform_create`:

```python
    def perform_create(self, serializer):
        from django.db import transaction
        from rest_framework.exceptions import ValidationError

        from .models import Payout, VendorWallet, WalletTransaction
        from .services import allocate_payout

        user = self.request.user
        amount = Decimal(str(self.request.data.get("amount", 0)))
        if amount <= 0:
            raise ValidationError({"amount": "Amount must be greater than zero."})

        with transaction.atomic():
            store = getattr(user, "store", None)
            if store is None:
                raise ValidationError({"store": "No store is associated with this account."})

            wallet, _ = VendorWallet.objects.select_for_update().get_or_create(
                user=user, store=store, defaults={"currency": "NGN"}
            )
            if wallet.available_balance < amount:
                raise ValidationError({"amount": "Insufficient available balance."})

            payout = serializer.save(
                vendor=user,
                store=store,
                amount=amount,
                reference=f"PO-{uuid.uuid4().hex[:12].upper()}",
            )
            allocate_payout(payout)

            VendorWallet.objects.filter(pk=wallet.pk).update(
                available_balance=F("available_balance") - amount
            )
            WalletTransaction.objects.create(
                wallet=wallet,
                transaction_type=WalletTransaction.Type.PAYOUT,
                amount=-amount,
                description=f"Payout request {payout.reference}",
                reference_id=str(payout.id),
            )

        process_payout_task.delay(payout.id)
```

Add `from django.db.models import F` to the imports. Remove the old generic `raise Exception`.

### Step 9.3 — Webhook transfer handlers

In `apps/commerce/webhooks.py`, replace the bodies of transfer success/failed/reversed with calls
to the services:

```python
    def _handle_transfer_success(self, data: dict) -> bool:
        from apps.financials.models import Payout
        from apps.financials.services import settle_payout

        reference = data.get("reference")
        payout = Payout.objects.filter(reference=reference).first()
        if payout is None:
            return False
        settle_payout(payout)
        return True

    def _handle_transfer_failed(self, data: dict) -> bool:
        from apps.financials.models import Payout
        from apps.financials.services import fail_payout

        reference = data.get("reference")
        payout = Payout.objects.filter(reference=reference).first()
        if payout is None:
            return False
        fail_payout(payout, data.get("reason") or "Transfer failed")
        return True

    def _handle_transfer_reversed(self, data: dict) -> bool:
        return self._handle_transfer_failed(data)
```

Delete the old manual wallet arithmetic. Keep `notify_payout_*` calls on commit.

### Step 9.4 — Admin mark-paid

Replace the body of `AdminMarkPayoutPaidView.post` after fetching the payout:

```python
        from apps.financials.services import settle_payout

        if payout.status == Payout.Status.PAID:
            return Response(
                {"error": "Payout already marked as paid."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not payout.allocations.exists():
            return Response(
                {"error": "Payout has no allocations and cannot be settled."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        settle_payout(payout)

        from apps.notifications.utils import notify_payout_processed
        notify_payout_processed(payout)

        AdminActionLog.log_action(
            admin_user=request.user,
            action_type="payout_marked_paid",
            description=f"Marked payout #{payout.pk} paid.",
        )
        return Response({"message": "Payout marked as paid."})
```

### Step 9.5 — Tests

Create `tests/test_payouts.py`:

```python
from decimal import Decimal

import pytest

from apps.financials.models import Payout, PayoutAllocation, VendorEarning
from apps.financials.services import allocate_payout, fail_payout, settle_payout
from tests.factories import PayoutFactory, VendorEarningFactory, VendorWalletFactory


def _released_earning(store, amount=Decimal("950.00")):
    earning = VendorEarningFactory(
        store=store,
        vendor=store.user,
        gross_amount=Decimal("1000.00"),
        status=VendorEarning.Status.AVAILABLE,
    )
    earning.released_amount = amount
    earning.save(update_fields=["released_amount"])
    return earning


@pytest.mark.django_db
def test_payout_settles_only_its_allocations():
    first_store = VendorEarningFactory().store
    first = _released_earning(first_store)
    second = _released_earning(first_store)

    payout = PayoutFactory(store=first_store, vendor=first_store.user, amount=Decimal("500.00"))
    allocate_payout(payout)
    settle_payout(payout)

    payout.refresh_from_db()
    first.refresh_from_db()
    second.refresh_from_db()
    assert payout.status == Payout.Status.PAID
    assert PayoutAllocation.objects.filter(payout=payout).count() == 1
    assert first.paid_out_amount == Decimal("500.00")
    assert second.paid_out_amount == Decimal("0.00")


@pytest.mark.django_db
def test_failed_payout_recredits_and_clears_allocations():
    store = VendorEarningFactory().store
    _released_earning(store)
    wallet = VendorWalletFactory(store=store, user=store.user, available_balance=Decimal("0.00"))
    payout = PayoutFactory(store=store, vendor=store.user, amount=Decimal("200.00"))

    allocate_payout(payout)
    fail_payout(payout, "bank rejected")

    payout.refresh_from_db()
    wallet.refresh_from_db()
    assert payout.status == Payout.Status.FAILED
    assert not payout.allocations.exists()
    assert wallet.available_balance == Decimal("200.00")


@pytest.mark.django_db
def test_over_withdrawal_is_rejected(api_client, auth_client):
    from tests.factories import StoreFactory

    store = StoreFactory()
    VendorWalletFactory(store=store, user=store.user, available_balance=Decimal("10.00"))
    client = auth_client(store.user)

    response = client.post(
        "/financials/payouts/",
        {
            "amount": "100.00",
            "bank_account": 1,
        },
        format="json",
    )

    assert response.status_code == 400
    assert not Payout.objects.exists()
```

> The payout route and required bank-account field may differ; read
> `apps/financials/urls.py` and `PayoutCreateSerializer`. Adjust the payload, keep the assertion
> that no payout is created and the status is 400.

Run:

```powershell
pytest tests/test_payouts.py -q
```

Expected: 3 passed.

Commit:

```powershell
git add apps/financials apps/commerce/webhooks.py apps/admin_panel/views.py tests/test_payouts.py
git commit -m "fix(payouts): allocate earnings per payout and settle only those allocations"
```

---

## Task 10 — Dispute authorisation and real refunds

**Why (D-04, D-11):** any authenticated user can refund any dispute, and the "refund" never calls
Paystack; it only moves internal numbers.

**Files**

- Modify: `apps/commerce/models.py` (`Refund`, `Payment.Status`)
- Create: `apps/commerce/services/refunds.py`
- Modify: `apps/commerce/paystack.py`
- Modify: `apps/commerce/views.py` (`DisputeActionView`)
- Modify: `apps/commerce/webhooks.py` (`refund.*`)
- Create: `tests/test_refunds.py`
- Create: `apps/commerce/migrations/000X_refund_model.py` (generated)

### Step 10.1 — Model

Add to `Payment.Status`:

```python
        PARTIALLY_REFUNDED = "partially_refunded", _("Partially refunded")
```

Add:

```python
class Refund(models.Model):
    """A gateway refund against a payment."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        PROCESSED = "processed", _("Processed")
        FAILED = "failed", _("Failed")

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, default="NGN")
    reason = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    reference = models.CharField(max_length=100, unique=True, blank=True)
    gateway_response = models.JSONField(default=dict, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "refunds"
        ordering = ["-created_at"]
```

### Step 10.2 — Paystack refund call

Add to `apps/commerce/paystack.py`:

```python
def initiate_refund(transaction_reference: str, amount_kobo: int | None = None,
                    reason: str = "") -> dict | None:
    """Request a refund. Returns the gateway data or None."""
    payload = {"transaction": transaction_reference}
    if amount_kobo is not None:
        payload["amount"] = amount_kobo
    if reason:
        payload["merchant_note"] = reason

    try:
        response = requests.post(
            f"{PAYSTACK_BASE_URL}/refund",
            json=payload,
            headers=_headers(),
            timeout=30,
        )
        data = response.json()
        if data.get("status"):
            return data["data"]
        logger.error("Paystack refund failed: %s", data)
    except Exception as exc:
        logger.exception("Paystack refund error: %s", exc)
    return None
```

### Step 10.3 — Refund service

Create `apps/commerce/services/refunds.py`:

```python
import logging
import uuid

from django.db import transaction
from django.utils import timezone

from apps.financials.services import money, reverse_earning

from ..models import Order, Payment, Refund
from ..paystack import initiate_refund

logger = logging.getLogger(__name__)


class RefundError(ValueError):
    pass


def request_refund(payment: Payment, amount, reason: str, actor) -> Refund:
    amount = money(amount)
    if amount <= 0:
        raise RefundError("Refund amount must be greater than zero.")
    if amount > payment.amount:
        raise RefundError("Refund amount exceeds payment amount.")
    if payment.status != Payment.Status.SUCCESS:
        raise RefundError("Only successful payments can be refunded.")

    data = initiate_refund(
        payment.reference,
        amount_kobo=int(amount * 100),
        reason=reason,
    )
    if data is None:
        raise RefundError("The payment gateway rejected the refund request.")

    refund = Refund.objects.create(
        payment=payment,
        amount=amount,
        currency=payment.currency,
        reason=reason,
        reference=data.get("reference") or f"RF-{uuid.uuid4().hex[:12].upper()}",
        gateway_response=data,
        requested_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    return refund


@transaction.atomic
def finalize_refund(refund: Refund, payload: dict | None = None):
    """Apply a gateway-confirmed refund exactly once."""
    from apps.financials.models import VendorEarning

    refund = Refund.objects.select_for_update().get(pk=refund.pk)
    if refund.status == Refund.Status.PROCESSED:
        return refund

    payment = Payment.objects.select_for_update().get(pk=refund.payment_id)
    refund.status = Refund.Status.PROCESSED
    refund.processed_at = timezone.now()
    if payload:
        refund.gateway_response = payload
    refund.save(update_fields=["status", "processed_at", "gateway_response"])

    payment.status = (
        Payment.Status.REFUNDED
        if refund.amount >= payment.amount
        else Payment.Status.PARTIALLY_REFUNDED
    )
    payment.save(update_fields=["status"])

    if payment.checkout_session_id:
        for order in payment.checkout_session.orders.select_for_update():
            order.status = Order.Status.CANCELLED
            order.save(update_fields=["status"])
            earning = VendorEarning.objects.filter(order=order).first()
            if earning:
                reverse_earning(earning, f"Refund {refund.reference} for order {order.order_number}")

    return refund
```

> If `initiate_refund` succeeds, Paystack sends `refund.processed`. In local debug the gateway is
> mocked, so tests call `finalize_refund` directly.

### Step 10.4 — Dispute view

Replace `DisputeActionView` with:

```python
class DisputeActionView(APIView):
    """Admin-only: resolve or refund a dispute."""

    permission_classes = [permissions.IsAuthenticated, HasAdminModulePermission]
    admin_module = AdminModule.SUPPORTS
    admin_require_manage = True

    @extend_schema(
        request=DisputeResolutionSerializer,
        responses={200: inline_serializer(
            name="DisputeActionResponse", fields={"message": serializers.CharField()}
        )},
    )
    def post(self, request, pk):
        from apps.commerce.services.refunds import RefundError, request_refund
        from apps.financials.models import VendorEarning

        dispute = get_object_or_404(Dispute, pk=pk)
        serializer = DisputeResolutionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data["action"]
        notes = serializer.validated_data["resolution_notes"]

        earning = VendorEarning.objects.filter(order=dispute.order).first()

        if action == "resolve":
            if earning:
                earning.is_disputed = False
                earning.save(update_fields=["is_disputed"])
            dispute.status = Dispute.Status.RESOLVED
            message = "Dispute resolved. Funds released to vendor escrow."

        elif action == "refund":
            payment = Payment.objects.filter(
                checkout_session=dispute.order.checkout_session
            ).first()
            if payment is None:
                return Response(
                    {"error": "No payment is linked to this order."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if earning:
                earning.is_disputed = True
                earning.save(update_fields=["is_disputed"])
            try:
                request_refund(
                    payment,
                    amount=payment.amount,
                    reason=notes or dispute.reason,
                    actor=request.user,
                )
            except RefundError as exc:
                return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
            dispute.status = Dispute.Status.UNDER_REVIEW
            message = "Refund requested. The dispute closes when the gateway confirms."

        else:
            return Response(
                {"error": "Invalid action."}, status=status.HTTP_400_BAD_REQUEST
            )

        dispute.resolution_notes = notes
        dispute.resolved_at = timezone.now() if action == "resolve" else None
        dispute.save(update_fields=["status", "resolution_notes", "resolved_at"])

        OrderActivity.objects.create(
            order=dispute.order,
            event_type=OrderActivity.EventType.OTHER,
            message=message,
        )
        return Response({"message": message})
```

Import `HasAdminModulePermission` and `AdminModule` at the top of `commerce/views.py`.

### Step 10.5 — Webhook refund handlers

Add to `apps/commerce/webhooks.py`:

```python
    def _handle_refund_processed(self, data: dict) -> bool:
        from apps.commerce.models import Refund
        from apps.commerce.services.refunds import finalize_refund

        reference = data.get("reference") or data.get("transaction_reference")
        refund = Refund.objects.filter(reference=reference).first()
        if refund is None:
            refund = Refund.objects.filter(payment__reference=reference).first()
        if refund is None:
            return False
        finalize_refund(refund, data)
        return True

    def _handle_refund_failed(self, data: dict) -> bool:
        from apps.commerce.models import Refund

        reference = data.get("reference") or data.get("transaction_reference")
        refund = Refund.objects.filter(reference=reference).first()
        if refund is None:
            return False
        refund.status = Refund.Status.FAILED
        refund.gateway_response = data
        refund.save(update_fields=["status", "gateway_response"])
        return True
```

### Step 10.6 — Tests

Create `tests/test_refunds.py`:

```python
from decimal import Decimal

import pytest
from rest_framework import status

from apps.commerce.models import Dispute, Payment, Refund
from apps.commerce.services.refunds import finalize_refund, request_refund
from apps.financials.models import VendorEarning
from apps.financials.services import accrue_earning
from tests.factories import OrderFactory, OrderItemFactory, PaymentFactory, UserFactory


@pytest.mark.django_db
def test_non_admin_cannot_refund(auth_client):
    order = OrderFactory()
    dispute = Dispute.objects.create(
        order=order, buyer=order.buyer, reason="broken", description="broken"
    )
    client = auth_client(UserFactory())

    response = client.post(
        f"/commerce/disputes/{dispute.pk}/action/",
        {"action": "refund", "resolution_notes": "give money back"},
        format="json",
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert not Refund.objects.exists()


@pytest.mark.django_db
def test_refund_reverses_earning_and_cancels_order(monkeypatch):
    order = OrderFactory()
    OrderItemFactory(order=order)
    payment = PaymentFactory(
        checkout_session=order.checkout_session,
        amount=order.total_amount,
        status=Payment.Status.SUCCESS,
    )
    earning = accrue_earning(order)

    monkeypatch.setattr(
        "apps.commerce.services.refunds.initiate_refund",
        lambda *args, **kwargs: {"reference": "RF-1", "status": "pending"},
    )
    refund = request_refund(payment, payment.amount, "damaged", actor=order.buyer)
    finalize_refund(refund, {"reference": "RF-1"})

    refund.refresh_from_db()
    payment.refresh_from_db()
    order.refresh_from_db()
    earning.refresh_from_db()
    assert refund.status == Refund.Status.PROCESSED
    assert payment.status == Payment.Status.REFUNDED
    assert order.status == "cancelled"
    assert earning.status == VendorEarning.Status.REVERSED
```

Run:

```powershell
python manage.py makemigrations commerce --name refund_model
python manage.py migrate --noinput
pytest tests/test_refunds.py -q
```

Expected: 2 passed.

Commit:

```powershell
git add apps/commerce tests/test_refunds.py
git commit -m "fix(disputes): require admin module permission and perform gateway refunds"
```

---

## Task 11 — Delete the empty health app

**Why (D-38):** `apps/health` has no URL, no model, and no use. Empty apps are noise.

**Files**

- Delete: `apps/health/`
- Modify: `hb/settings.py`

Steps:

```powershell
Remove-Item -Recurse -Force apps/health
```

Remove `"apps.health",` from `LOCAL_APPS` in `hb/settings.py`.

Run:

```powershell
python manage.py check
pytest -q
```

Commit:

```powershell
git add -A
git commit -m "chore: remove unused health app"
```

---

## Task 12 — Data reconciliation command

**Why:** production has live orders and earnings created before the fixes. The command repairs
judgement-based data without deleting anything.

**Files**

- Create: `apps/commerce/management/__init__.py`
- Create: `apps/commerce/management/commands/__init__.py`
- Create: `apps/commerce/management/commands/reconcile_orders.py`
- Create: `tests/test_reconcile_orders.py`

### Step 12.1 — Command

Create `apps/commerce/management/commands/reconcile_orders.py`:

```python
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.commerce.models import Order
from apps.financials.models import VendorEarning, VendorWallet


class Command(BaseCommand):
    help = "Repair pre-P0 orders, stores, and earnings without deleting data."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write changes.")
        parser.add_argument("--dry-run", action="store_true", help="Print changes only.")

    def handle(self, *args, **options):
        apply = options["apply"]
        if not apply:
            self.stdout.write(self.style.WARNING("DRY RUN — pass --apply to write."))

        changed = {"orders": 0, "earnings": 0, "wallets": 0, "fees": 0}

        for order in Order.objects.all().iterator():
            updates = []
            item = order.items.select_related("listing__store").first()
            if item and not order.store_id and item.listing and item.listing.store_id:
                order.store_id = item.listing.store_id
                updates.append("store")
            if order.store_id and order.seller_id != order.store.user_id:
                order.seller_id = order.store.user_id
                updates.append("seller")
            if order.status == Order.Status.PENDING_PAYMENT and order.escrow_fee:
                order.total_amount = max(order.total_amount - order.escrow_fee, Decimal("0.00"))
                order.escrow_fee = Decimal("0.00")
                updates.extend(["total_amount", "escrow_fee"])
                changed["fees"] += 1
            if updates:
                changed["orders"] += 1
                self.stdout.write(f"Order {order.pk}: {', '.join(sorted(set(updates)))}")
                if apply:
                    order.save(update_fields=sorted(set(updates)))

        for earning in VendorEarning.objects.filter(order__isnull=False).iterator():
            order = earning.order
            if order.status not in (Order.Status.PAID, Order.Status.FULFILLED):
                continue
            if order.currency != "NGN":
                continue
            wallet, created = VendorWallet.objects.get_or_create(
                user=earning.vendor,
                store=earning.store,
                defaults={"currency": earning.currency},
            )
            if created:
                changed["wallets"] += 1
                self.stdout.write(f"Wallet created for {earning.vendor_id}/{earning.store_id}")

        if apply:
            self.stdout.write(self.style.SUCCESS(f"Applied: {changed}"))
        else:
            self.stdout.write(self.style.WARNING(f"Would apply: {changed}"))
```

The command deliberately does **not** invent orders or prices. It reports what it cannot repair.

### Step 12.2 — Test

Create `tests/test_reconcile_orders.py`:

```python
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from apps.commerce.models import Order
from tests.factories import OrderFactory


@pytest.mark.django_db
def test_command_zeroes_unpaid_buyer_fee_only():
    order = OrderFactory(
        escrow_fee=Decimal("50.00"),
        subtotal=Decimal("1000.00"),
        total_amount=Decimal("1050.00"),
        status=Order.Status.PENDING_PAYMENT,
    )
    out = StringIO()

    call_command("reconcile_orders", "--apply", stdout=out)

    order.refresh_from_db()
    assert order.escrow_fee == Decimal("0.00")
    assert order.total_amount == Decimal("1000.00")


@pytest.mark.django_db
def test_command_does_not_rewrite_paid_totals():
    order = OrderFactory(
        escrow_fee=Decimal("50.00"),
        subtotal=Decimal("1000.00"),
        total_amount=Decimal("1050.00"),
        status=Order.Status.PAID,
    )
    call_command("reconcile_orders", "--apply", stdout=StringIO())

    order.refresh_from_db()
    assert order.total_amount == Decimal("1050.00")
```

Run:

```powershell
pytest tests/test_reconcile_orders.py -q
```

Expected: 2 passed.

Commit:

```powershell
git add apps/commerce/management tests/test_reconcile_orders.py
git commit -m "feat(commerce): add non-destructive order reconciliation command"
```

---

## Task 13 — Full verification and handoff

### Step 13.1 — Run everything

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
pytest -q
flake8 apps hb --select=F821 --exclude=migrations
```

Expected:

- `check` reports no issues.
- `makemigrations --check` reports no changes.
- All tests pass.
- flake8 reports no `F821` (undefined names). F401/F841 are cleaned up in P3.

### Step 13.2 — Manual acceptance against a staging database

Use two accounts (buyer, seller) and one admin. Perform:

1. `POST /auth/register/` with `"role": "super_admin"` → `400`.
2. Register a buyer normally → `201`, `role == "buyer"`.
3. Seller completes onboarding step 3 with two files → `VerificationRequest.business_type ==
   "sole_proprietorship"`, `additional_info == ""`, and the admin vendor drawer shows exactly two
   document URLs, both starting with the media/S3 host.
4. Seller creates a listing with `store=<another store>` → the listing is saved under the seller's
   store.
5. Buyer adds a rental item and checks out → order total equals subtotal, no fee, order item
   `purchase_type == "hire"`.
6. Simulate `charge.success` twice with the same `data.id` → one `WebhookEvent`, one
   `VendorEarning`, one pending wallet credit.
7. Call `GET /commerce/payment/verify/<reference>/` while pending → `pending_confirmation`, and
   `Payment.status` stays `pending`.
8. Request a payout → `PayoutAllocation` rows sum to the payout amount. Mark it paid → only those
   earnings change.
9. Open a dispute as buyer; call the action endpoint as a non-admin → `403`; as support admin with
   manage permission → Paystack refund request is made and a `Refund` row exists.
10. Run `python manage.py reconcile_orders --dry-run` → only expected changes printed.

### Step 13.3 — Update the changelog

Create `docs/superpowers/plans/P0-COMPLETE.md`:

```markdown
# P0 complete

- Test harness and CI: `pytest`, PostgreSQL service, migration check, schema validation.
- Auth: registration forces buyer; token blacklist installed.
- Admin: dashboard staff identity and module matrix enforced on every endpoint.
- Listings: store derived server-side, backfilled, non-null.
- Verification: business type stored separately; fake document paths removed.
- Checkout: no buyer fee; rent maps to hire.
- Money: one earning per order; release/reversal services.
- Payments: single idempotent finalizer; webhook ledger; read-only verify; reconciler.
- Payouts: allocation-bound settlement; failure re-credit.
- Refunds: admin-only, gateway-backed, webhook-finalised.
- Health app removed; reconciliation command added.

Next: P1 (every 500 and dead feature).
```

Commit:

```powershell
git add docs/superpowers/plans/P0-COMPLETE.md
git commit -m "docs: record P0 completion and verification"
```

---

## Rollback

If P0 must be reverted in production:

1. Stop the web, worker, and beat services.
2. `git revert` the P0 merge commit. Do not run reverse migrations on data-bearing tables without a
   database snapshot.
3. Take a snapshot before deploying. The only irreversible data operation in P0 is the store
   backfill; it creates stores and assigns listings. Reverting the code leaves those rows in place,
   which is harmless.

## Definition of done

- [ ] `pytest -q` green.
- [ ] `python manage.py makemigrations --check --dry-run` clean.
- [ ] `python manage.py check` clean.
- [ ] Registering `role=super_admin` returns `400`; no user row created.
- [ ] Duplicate `charge.success` creates one earning.
- [ ] Verify is read-only.
- [ ] Payout settlement touches only its allocations.
- [ ] Non-admin gets `403` on every `/admin-panel/` route.
- [ ] Listing create with a foreign `store` ignores it.
- [ ] Vendor drawer has no `sole_proprietorship` document.
- [ ] Checkout total has no buyer fee; rental orders are `hire`.
- [ ] Deploy no longer runs `create_sample_data`.
