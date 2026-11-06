# P5 Zero-Debt Alignment — Implementation Plan

> **For the executor:** This plan is written for a developer who does not know this codebase.
> Follow the tasks in order. Do not skip a gate. Do not reset, truncate or reseed any database.
> One commit per task, only after the full gate passes.

**Goal:** Close every remaining gap between the approved P5 design and the running code, so that
every configuration flag changes real behaviour, every declared response field exists, every
notification channel works, every operational model is in the Django admin, and every document
matches the code.

**Design spec:**
[`docs/superpowers/specs/2026-11-02-harbour-hub-zero-debt-alignment-design.md`](../specs/2026-11-02-harbour-hub-zero-debt-alignment-design.md)

**Baseline commit:** `99ab351` (`docs: add the P5 zero-debt alignment design`)

**Architecture:** Django 4.2 + DRF, PostgreSQL, Celery + Redis, Paystack for payments, Termii for
SMS, Web Push (VAPID) for browser push. Money is NGN `Decimal`. Buyers pay no platform fee; the
platform earns a seller-side commission on the goods subtotal only.

**Runtime commands (Windows PowerShell, from the repository root):**

```powershell
python -m pytest <paths> -q
python manage.py makemigrations --check --dry-run
python -m flake8 apps hb --select=F401,F821,F841 --exclude=migrations
python manage.py spectacular --file schema.yml --validate
```

The local database `harbour_hub` already has the P0–P4 migrations. Tests run against
`test_harbour_hub`. **Never switch to SQLite and never run `flush`, `reset_db` or
`create_sample_data --force` against `harbour_hub`.**

---

## The gate — run before every commit

Every task ends with this exact sequence. Do not commit if any step fails.

```powershell
# 1. The task's focused tests
python -m pytest <task test paths> -q

# 2. The whole suite
python -m pytest -q

# 3. No missing migrations
python manage.py makemigrations --check --dry-run

# 4. No undefined names or unused imports in changed code
python -m flake8 apps hb --select=F401,F821,F841 --exclude=migrations

# 5. The OpenAPI schema still validates
python manage.py spectacular --file schema.yml --validate
```

Commit format:

```text
<type>(<scope>): <imperative summary>

<body: what changed and why>

Gate: pytest <n> passed; makemigrations clean; flake8 F-checks clean; schema valid.
```

---

## Task map

| # | Task | Primary areas | Test files |
|---|---|---|---|
| 1 | Platform config endpoint, listing type/approval enforcement, admin bulk publish | `admin_panel`, `listings`, `store`, `categories`, `core` | `tests/test_platform_config.py`, `tests/test_listing_policies.py` |
| 2 | Vendor approval automation and verification response contract | `accounts` | `tests/test_vendor_approval.py` |
| 3 | Checkout delivery fee, delivery snapshot, invoice wording | `commerce` | `tests/test_checkout_delivery.py`, `tests/test_invoice.py` |
| 4 | Payout/earning state machine and dispute lifecycle | `financials`, `commerce` | `tests/test_payout_state_machine.py`, `tests/test_dispute_lifecycle.py` |
| 5 | Notifications: push, preferences, SMS cleanup, wording, admin | `notifications` | `tests/test_notification_channels.py`, `tests/test_notification_preferences.py` |
| 6 | Social login hardening, admin coverage, real analytics export | `accounts`, `admin_panel`, all admin modules | `tests/test_social_auth.py`, `tests/test_admin_coverage.py`, `tests/test_analytics_export.py` |
| 7 | Correctness fixes: routes, webhook alias, session device type, commission fields | `commerce`, `accounts`, `financials` | `tests/test_routes.py`, `tests/test_sessions.py`, `tests/test_order_contract.py`, `tests/test_financial_contract.py` |
| 8 | Config, dependencies, CI/deploy, docs, backlog, schema, completion record | repo-wide | `tests/test_check_paystack_config.py` |
| 9 | Production Paystack cutover (operational, not a code commit) | server | manual verification |

Tasks 1–8 each produce exactly one commit. Task 9 produces no repository commit; it records its
evidence in `docs/superpowers/plans/P5-COMPLETE.md` after the deploy.

---

## Task 1 — Platform config endpoint, listing type/approval enforcement, admin bulk publish

**Why:** `PlatformConfig` exists but changes nothing. Three flags must gate listing creation,
public discovery and publishing, and the public contract must be readable without a token. The
Django admin bulk action must stop producing published rows with a null `published_at`.

### Files

| Action | Path |
|---|---|
| Create | `apps/listings/public.py` |
| Edit | `apps/listings/serializers.py` |
| Edit | `apps/listings/views.py` |
| Edit | `apps/listings/permissions.py` (allow admins to use POST actions) |
| Edit | `apps/listings/admin.py` (remove `ListingStatusUpdateSerializer` usage if imported) |
| Edit | `apps/store/views.py`, `apps/store/serializers.py` |
| Edit | `apps/categories/models.py` |
| Edit | `apps/core/views.py` |
| Edit | `apps/admin_panel/serializers.py`, `apps/admin_panel/views.py` |
| Edit | `hb/api_urls_v1.py` |
| Create | `tests/test_platform_config.py` |
| Create | `tests/test_listing_policies.py` |
| Edit | `tests/test_listings.py` (owner publish test disables approval) |

### Step 1.1 — Write the failing tests

Create `tests/test_platform_config.py`:

```python
import pytest
from rest_framework.test import APIClient

from apps.admin_panel.models import PlatformConfig


@pytest.mark.django_db
def test_platform_config_is_public_and_matches_the_contract():
    response = APIClient().get("/platform-config/")

    assert response.status_code == 200
    assert response.data == {
        "enable_buy": True,
        "enable_rent": True,
        "enable_services": False,
        "vendor_approval_required": True,
        "listing_approval_required": True,
        "default_currency": "NGN",
        "timezone": "Africa/Lagos",
        "date_format": "DD/MM/YY",
    }


@pytest.mark.django_db
def test_platform_config_reflects_saved_changes():
    config = PlatformConfig.objects.get_or_create(pk=1)[0]
    config.enable_rent = False
    config.default_currency = "USD"
    config.save()

    response = APIClient().get("/platform-config/")

    assert response.status_code == 200
    assert response.data["enable_rent"] is False
    assert response.data["default_currency"] == "USD"
```

Create `tests/test_listing_policies.py`:

```python
from datetime import timedelta

import pytest
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.admin_panel.models import PlatformConfig
from apps.listings.admin import ListingAdmin
from apps.listings.models import Listing
from tests.factories import (
    CategoryFactory,
    ListingFactory,
    StoreFactory,
    UserFactory,
)


def _config(**overrides):
    config = PlatformConfig.objects.get_or_create(pk=1)[0]
    for key, value in overrides.items():
        setattr(config, key, value)
    config.save()
    return config


def _seller_with_store():
    store = StoreFactory()
    return store.user, store


def _payload(_store, **overrides):
    payload = {
        "title": "Hydraulic winch",
        "description": "Heavy duty winch in good condition.",
        "category": CategoryFactory().pk,
        "listing_type": Listing.Type.SELL,
        "price": "1500000.00",
        "location": "Lagos",
        "contact_name": "Test Seller",
        "contact_email": "seller@example.com",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_create_rejects_a_disabled_listing_type(auth_client):
    _config(enable_buy=False)
    seller, store = _seller_with_store()
    payload = _payload(store)

    response = auth_client(seller).post("/listings/", payload, format="json")

    assert response.status_code == 400
    assert response.data["listing_type"] == ["Buy listings are currently disabled."]


@pytest.mark.django_db
def test_create_stores_draft_when_approval_is_required(auth_client):
    _config(listing_approval_required=True)
    seller, store = _seller_with_store()

    response = auth_client(seller).post(
        "/listings/", _payload(store, status="published"), format="json"
    )

    assert response.status_code == 201
    listing = Listing.objects.get(pk=response.data["id"])
    assert listing.status == Listing.Status.DRAFT
    assert listing.published_at is None


@pytest.mark.django_db
def test_create_publishes_immediately_when_approval_is_not_required(auth_client):
    _config(listing_approval_required=False)
    seller, store = _seller_with_store()

    response = auth_client(seller).post("/listings/", _payload(store), format="json")

    assert response.status_code == 201
    listing = Listing.objects.get(pk=response.data["id"])
    assert listing.status == Listing.Status.PUBLISHED
    assert listing.published_at is not None


@pytest.mark.django_db
def test_update_cannot_publish_a_never_approved_listing(auth_client):
    _config(listing_approval_required=True)
    seller, store = _seller_with_store()
    listing = ListingFactory(user=seller, store=store, status=Listing.Status.DRAFT)

    response = auth_client(seller).patch(
        f"/listings/{listing.pk}/", {"status": "published"}, format="json"
    )

    assert response.status_code == 400
    assert response.data["status"] == [
        "Listings require admin approval before publishing."
    ]


@pytest.mark.django_db
def test_publish_action_enforces_approval(auth_client):
    _config(listing_approval_required=True)
    seller, store = _seller_with_store()
    listing = ListingFactory(user=seller, store=store, status=Listing.Status.DRAFT)
    store.is_active = True
    store.save(update_fields=["is_active"])

    response = auth_client(seller).post(f"/listings/{listing.pk}/publish/")

    assert response.status_code == 400
    assert response.data["error"] == (
        "Listings require admin approval before publishing."
    )


@pytest.mark.django_db
def test_admin_may_publish_a_draft(auth_client):
    _config(listing_approval_required=True)
    seller, store = _seller_with_store()
    listing = ListingFactory(user=seller, store=store, status=Listing.Status.DRAFT)
    admin = UserFactory(role=User.Role.ADMIN, is_staff=True)

    response = auth_client(admin).post(f"/listings/{listing.pk}/publish/")

    assert response.status_code == 200
    listing.refresh_from_db()
    assert listing.status == Listing.Status.PUBLISHED
    assert listing.published_at is not None


@pytest.mark.django_db
def test_public_list_hides_a_disabled_type():
    _config(enable_services=False)
    seller, store = _seller_with_store()
    visible = ListingFactory(
        user=seller, store=store, listing_type=Listing.Type.SELL,
        status=Listing.Status.PUBLISHED, published_at=timezone.now(),
    )
    hidden = ListingFactory(
        user=seller, store=store, listing_type=Listing.Type.SERVICE,
        status=Listing.Status.PUBLISHED, published_at=timezone.now(),
    )

    response = APIClient().get("/listings/")
    ids = {row["id"] for row in response.data["results"]}

    assert visible.pk in ids
    assert hidden.pk not in ids


@pytest.mark.django_db
def test_owner_can_still_retrieve_a_disabled_type(auth_client):
    _config(enable_services=False)
    seller, store = _seller_with_store()
    listing = ListingFactory(
        user=seller, store=store, listing_type=Listing.Type.SERVICE,
        status=Listing.Status.PUBLISHED, published_at=timezone.now(),
    )

    response = auth_client(seller).get(f"/listings/{listing.pk}/")

    assert response.status_code == 200


@pytest.mark.django_db
def test_forged_store_is_ignored(auth_client):
    _config(listing_approval_required=False)
    seller, store = _seller_with_store()
    other_store = StoreFactory()

    response = auth_client(seller).post(
        "/listings/", _payload(store, store=other_store.pk), format="json"
    )

    assert response.status_code == 201
    listing = Listing.objects.get(pk=response.data["id"])
    assert listing.store_id == store.pk


@pytest.mark.django_db
def test_admin_bulk_publish_sets_published_at(monkeypatch):
    listing = ListingFactory(status=Listing.Status.DRAFT)
    model_admin = ListingAdmin(Listing, AdminSite())
    monkeypatch.setattr(model_admin, "message_user", lambda *a, **k: None)

    model_admin.mark_published(
        RequestFactory().post("/admin/"),
        Listing.objects.filter(pk=listing.pk),
    )

    listing.refresh_from_db()
    assert listing.status == Listing.Status.PUBLISHED
    assert listing.published_at is not None
```

Public-endpoint tests use `APIClient()` with no credentials so the request is genuinely
anonymous; authenticated tests use the `auth_client` fixture.

`tests/test_listings.py::test_owner_can_publish_a_draft` must disable
`listing_approval_required` first. It tests the owner publish path, not the approval gate; the
approval gate is covered by `test_publish_action_enforces_approval` above.

Run the tests. They must fail for the right reasons (404 on `/platform-config/`, 201 where 400 is
expected, disabled types still visible).

### Step 1.2 — Implement `apps/listings/public.py`

```python
"""Single source of truth for public listing visibility.

Every public surface must use these helpers so the enabled-type and published rules
cannot drift between the listing list, detail, recommendations, search, stores and
category counts.
"""
from django.db.models import Q

from apps.admin_panel.models import PlatformConfig

from .models import Listing

TYPE_FLAGS = {
    Listing.Type.SELL: "enable_buy",
    Listing.Type.RENT: "enable_rent",
    Listing.Type.LEASE: "enable_rent",
    Listing.Type.SERVICE: "enable_services",
}

DISABLED_TYPE_MESSAGES = {
    Listing.Type.SELL: "Buy listings are currently disabled.",
    Listing.Type.RENT: "Rent and lease listings are currently disabled.",
    Listing.Type.LEASE: "Rent and lease listings are currently disabled.",
    Listing.Type.SERVICE: "Service listings are currently disabled.",
}

OWNER_SETTABLE_STATUSES = {
    Listing.Status.DRAFT,
    Listing.Status.PUBLISHED,
    Listing.Status.PAUSED,
    Listing.Status.ARCHIVED,
}

APPROVAL_REQUIRED_ERROR = (
    "Listings require admin approval before publishing."
)


def get_platform_config():
    """Return the singleton config, creating defaults on first read."""
    return PlatformConfig.get()


def is_admin(user):
    return bool(
        user
        and user.is_authenticated
        and (user.is_staff or user.is_superuser or user.is_admin_user)
    )


def enabled_listing_types(config=None):
    config = config or get_platform_config()
    return [
        listing_type
        for listing_type, flag in TYPE_FLAGS.items()
        if getattr(config, flag)
    ]


def enabled_types_q(prefix=""):
    """Q object restricting a queryset to enabled listing types."""
    return Q(**{f"{prefix}listing_type__in": enabled_listing_types()})


def public_listing_q():
    """Published, active-store, enabled-type."""
    return (
        Q(status=Listing.Status.PUBLISHED)
        & Q(store__is_active=True)
        & enabled_types_q()
    )


def public_listings(queryset=None):
    queryset = queryset if queryset is not None else Listing.objects.all()
    return queryset.filter(public_listing_q())


def validate_listing_type_enabled(listing_type, config=None):
    """Return an error string when the type is disabled, else None."""
    config = config or get_platform_config()
    flag = TYPE_FLAGS.get(listing_type)
    if flag and not getattr(config, flag):
        return DISABLED_TYPE_MESSAGES[listing_type]
    return None


def can_publish(listing, user, config=None):
    """Approval rule shared by the serializer and the publish action."""
    if is_admin(user):
        return True
    config = config or get_platform_config()
    if not config.listing_approval_required:
        return True
    return listing.published_at is not None
```

### Step 1.3 — Enforce in `ListingCreateUpdateSerializer`

In `validate()`, keep the existing request-file extraction, image-count limit, featured
permission check and `service_area` fill, then add the policy checks. The merged method is:

```python
def validate(self, attrs):
    request = self.context.get("request")
    user = getattr(request, "user", None)
    config = get_platform_config()

    # Existing behaviour: pull repeated file fields from request.FILES manually.
    if request and hasattr(request, "FILES"):
        images = request.FILES.getlist("images_data")
        if images:
            attrs["images_data"] = images

        documents = request.FILES.getlist("documents_data")
        if documents:
            attrs["documents_data"] = documents

    images_data = attrs.get("images_data", [])
    existing_count = self.instance.images.count() if self.instance else 0
    max_images = 5
    if existing_count + len(images_data) > max_images:
        raise serializers.ValidationError(
            f"A listing can have a maximum of {max_images} images. "
            f"You currently have {existing_count}, trying to add "
            f"{len(images_data)}."
        )

    if self.instance and "featured" in attrs and user != self.instance.user:
        raise serializers.ValidationError(
            "You can only change featured flag for your own listings."
        )

    incoming_type = attrs.get("listing_type")
    current_type = getattr(self.instance, "listing_type", None)
    type_changed = self.instance is None or (
        incoming_type is not None and incoming_type != current_type
    )
    if type_changed and incoming_type:
        error = validate_listing_type_enabled(incoming_type, config)
        if error:
            raise serializers.ValidationError({"listing_type": [error]})

    incoming_status = attrs.get("status")
    if (
        incoming_status in (Listing.Status.FLAGGED, Listing.Status.SUSPENDED)
        and not is_admin(user)
    ):
        raise serializers.ValidationError(
            {"status": ["This status can only be set by an administrator."]}
        )

    if self.instance is None:
        if is_admin(user):
            attrs["status"] = incoming_status or Listing.Status.DRAFT
        elif config.listing_approval_required:
            # Every seller-created listing waits for approval.
            attrs["status"] = Listing.Status.DRAFT
        else:
            attrs["status"] = incoming_status or Listing.Status.PUBLISHED
    elif (
        incoming_status == Listing.Status.PUBLISHED
        and not can_publish(self.instance, user, config)
    ):
        raise serializers.ValidationError(
            {"status": [APPROVAL_REQUIRED_ERROR]}
        )

    if attrs.get("listing_type") == Listing.Type.SERVICE and not attrs.get(
        "service_area"
    ):
        attrs["service_area"] = attrs.get("location", "")
    return attrs
```

Imports at the top of `apps/listings/serializers.py`:

```python
from .public import (
    APPROVAL_REQUIRED_ERROR,
    can_publish,
    get_platform_config,
    is_admin,
    validate_listing_type_enabled,
)
```

Delete the unused `ListingStatusUpdateSerializer` from that file and any import of it.

### Step 1.3b — Let admins use the POST actions

`CanCreateListing.has_permission` only inspects `can_create_listings`, which is false for the
`ADMIN` and `SUPER_ADMIN` roles even though `publish`, `archive` and `pause` are POST actions the
admin must be able to call. `apps/listings/permissions.py`:

```python
def has_permission(self, request, view):
    if request.method == "POST":
        if not (request.user and request.user.is_authenticated):
            return False
        if getattr(request.user, "is_admin_user", False) or request.user.is_staff:
            return True
        can_create = getattr(request.user, "can_create_listings", False)
        if callable(can_create):
            return can_create()
        return bool(can_create)
    return True
```

Admins still cannot create a listing through `POST /listings/` because `create()` requires the
owner to have a store; this change only unblocks the publish/archive/pause actions.

### Step 1.4 — Use the helper on every public surface

`apps/listings/views.py` — replace `public_filter` with `public_listing_q()`:

```python
from .public import (
    APPROVAL_REQUIRED_ERROR, can_publish, get_platform_config,
    is_admin, public_listing_q, public_listings,
)

def get_queryset(self):
    queryset = super().get_queryset()
    public_filter = public_listing_q()

    if self.action == "list":
        return queryset.filter(public_filter)
    if self.action == "retrieve":
        user = self.request.user
        if user and user.is_authenticated:
            if is_admin(user):
                return queryset
            return queryset.filter(public_filter | Q(user=user))
        return queryset.filter(public_filter)
    return queryset
```

`publish` action, before the store check:

```python
config = get_platform_config()
if not can_publish(listing, request.user, config):
    return Response(
        {"error": APPROVAL_REQUIRED_ERROR},
        status=status.HTTP_400_BAD_REQUEST,
    )
```

`TopDealsListView.get_queryset` and `BestReviewedListView.get_queryset`: start from
`public_listings(Listing.objects.all())` instead of the hand-written status/store filter.

`apps/core/views.py` global search: replace the `status`/store filters with
`public_listings(Listing.objects.filter(<search Q>))`.

`apps/store/views.py`:

- `annotate_store_for_top_vendors`: add `listings__listing_type__in=enabled_listing_types()`
  to the `published_listing_count` filter.
- `_public_directory_queryset` / `_store_detail_queryset` prefetches stay as they are; the
  serializer filters.

`apps/store/serializers.py`, `StoreDirectoryListingPreviewMixin` — both the count and the
preview list must respect the enabled types:

```python
from apps.listings.public import enabled_listing_types

def _public_store_listings(self, obj):
    return obj.listings.filter(
        status=Listing.Status.PUBLISHED,
        listing_type__in=enabled_listing_types(),
    )

@extend_schema_field(serializers.IntegerField())
def get_listing_count(self, obj):
    return self._public_store_listings(obj).count()

@extend_schema_field(StoreListingMiniSerializer(many=True))
def get_listings(self, obj):
    limit = self.context.get("listing_limit", 6)
    base = self._public_store_listings(obj)
    featured_list = list(base.filter(featured=True).order_by("-created_at")[:limit])
    remaining = limit - len(featured_list)
    if remaining > 0:
        featured_ids = [item.id for item in featured_list]
        recent_list = list(
            base.exclude(id__in=featured_ids).order_by("-created_at")[:remaining]
        )
        listings = featured_list + recent_list
    else:
        listings = featured_list
    return StoreListingMiniSerializer(listings, many=True).data
```

`apps/categories/models.py` `get_listing_count`: add
`listing_type__in=enabled_listing_types()`. Import the helper lazily inside the method to avoid an
import cycle:

```python
from apps.listings.public import enabled_listing_types
```

### Step 1.5 — Public endpoint

`apps/admin_panel/serializers.py`:

```python
class PublicPlatformConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformConfig
        fields = (
            "enable_buy", "enable_rent", "enable_services",
            "vendor_approval_required", "listing_approval_required",
            "default_currency", "timezone", "date_format",
        )
        read_only_fields = fields
```

`apps/admin_panel/views.py`:

```python
class PublicPlatformConfigView(APIView):
    """Unauthenticated marketplace switches for the web and mobile clients."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    @extend_schema(
        summary="Public platform configuration",
        responses={200: PublicPlatformConfigSerializer},
    )
    def get(self, request):
        return Response(PublicPlatformConfigSerializer(PlatformConfig.get()).data)
```

`hb/api_urls_v1.py`, immediately after the auth block:

```python
from apps.admin_panel.views import PublicPlatformConfigView

path("platform-config/", PublicPlatformConfigView.as_view(), name="platform-config"),
```

### Step 1.6 — Django admin bulk publish

`apps/listings/admin.py`:

```python
def mark_published(self, request, queryset):
    now = timezone.now()
    for listing in queryset:
        listing.status = Listing.Status.PUBLISHED
        if listing.published_at is None:
            listing.published_at = now
        listing.save(update_fields=["status", "published_at", "updated_at"])
    self.message_user(request, f"{queryset.count()} listing(s) published.")
```

Add `from django.utils import timezone`.

### Step 1.7 — Gate and commit

```powershell
python -m pytest tests/test_platform_config.py tests/test_listing_policies.py -q
python -m pytest -q
python manage.py makemigrations --check --dry-run
python -m flake8 apps hb --select=F401,F821,F841 --exclude=migrations
python manage.py spectacular --file schema.yml --validate
```

Commit:

```text
feat(listings): enforce platform config on listing lifecycle and public reads

PlatformConfig now drives enabled marketplace types, approval on create,
update and the publish action, the public listing/search/store/category
surfaces, and the Django admin bulk publish action. Adds the public
GET /platform-config/ contract and removes the unused
ListingStatusUpdateSerializer.
```

---

## Task 2 — Vendor approval automation and verification response contract

**Why:** `vendor_approval_required` currently changes nothing, and the verification endpoint
declares one response shape while returning another.

**Already done — do not duplicate:** the one-time store backfill ships as data migration
`apps/listings/migrations/0009_backfill_listing_stores.py`, which links legacy null-store
listings to the owner's store (creating a store when the owner has none), and
`0010_listing_store_required.py` made `Listing.store` non-null. There is no runtime command to
add, and `store__isnull=True` can no longer match in the current schema.

### Files

| Action | Path |
|---|---|
| Edit | `apps/accounts/views.py` |
| Edit | `apps/accounts/serializers.py` (verification response serializer + onboarding store) |
| Create | `tests/test_vendor_approval.py` |

### Step 2.1 — Write the failing tests

Create `tests/test_vendor_approval.py`:

```python
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import VerificationRequest
from apps.admin_panel.models import PlatformConfig
from apps.store.models import Store
from tests.factories import StoreFactory


def _config(**overrides):
    config = PlatformConfig.objects.get_or_create(pk=1)[0]
    for key, value in overrides.items():
        setattr(config, key, value)
    config.save()
    return config


def _provider_with_store():
    store = StoreFactory(user__role="service_provider")
    return store.user, store


def _payload():
    return {
        "company_name": "Acme Oilfield Services",
        "business_type": "limited_liability",
        "business_license": SimpleUploadedFile(
            "license.pdf", b"%PDF-1.4 test", content_type="application/pdf"
        ),
        "certifications": "API 610",
    }


@pytest.mark.django_db
def test_request_stays_pending_when_approval_is_required(auth_client):
    _config(vendor_approval_required=True)
    user, store = _provider_with_store()

    with patch(
        "apps.accounts.views.notify_admins_verification_request.delay"
    ) as notify_admins, patch(
        "apps.accounts.views.notify_verification_approved"
    ) as notify_approved:
        response = auth_client(user).post(
            "/auth/verification/request/", _payload(), format="multipart"
        )

    assert response.status_code == 201
    request_obj = VerificationRequest.objects.get(user=user)
    assert request_obj.status == VerificationRequest.Status.PENDING
    assert request_obj.reviewed_at is None
    user.refresh_from_db()
    store.refresh_from_db()
    assert user.is_verified is False
    assert store.is_verified is False
    assert response.data["status"] == "pending"
    assert response.data["request_id"] == request_obj.pk
    assert response.data["message"] == (
        "Verification request submitted successfully"
    )
    notify_admins.assert_called_once()
    notify_approved.assert_not_called()


@pytest.mark.django_db
def test_request_is_auto_approved_when_approval_is_disabled(auth_client):
    _config(vendor_approval_required=False)
    user, store = _provider_with_store()

    with patch(
        "apps.accounts.views.notify_admins_verification_request.delay"
    ) as notify_admins, patch(
        "apps.accounts.views.notify_verification_approved"
    ) as notify_approved:
        response = auth_client(user).post(
            "/auth/verification/request/", _payload(), format="multipart"
        )

    assert response.status_code == 201
    request_obj = VerificationRequest.objects.get(user=user)
    assert request_obj.status == VerificationRequest.Status.APPROVED
    assert request_obj.reviewed_by is None
    assert request_obj.reviewed_at is not None
    assert request_obj.admin_notes == (
        "Auto-approved because vendor approval is disabled."
    )
    user.refresh_from_db()
    store.refresh_from_db()
    assert user.is_verified is True
    assert store.is_verified is True
    assert response.data["status"] == "approved"
    notify_admins.assert_not_called()
    notify_approved.assert_called_once_with(user)


@pytest.mark.django_db
def test_onboarding_creates_verified_store_when_approval_is_disabled(
    auth_client, monkeypatch
):
    _config(vendor_approval_required=False)
    monkeypatch.setattr(
        "apps.accounts.serializers.notify_verification_approved",
        lambda user: None,
        raising=False,
    )
    seller = StoreFactory().user
    Store.objects.filter(user=seller).delete()
    seller.role = "seller"
    seller.save(update_fields=["role"])

    response = auth_client(seller).post(
        "/auth/onboarding/step-1/",
        {
            "business_name": "Delta Marine Supply",
            "phone": "08030000000",
            "email": "delta@example.com",
            "country": "Nigeria",
        },
        format="json",
    )

    assert response.status_code in (200, 201)
    store = Store.objects.get(user=seller)
    assert store.is_verified is True
```

> The onboarding route is `POST /auth/onboarding/step-1/`; the behaviour under test is what
> matters: a **newly created** store is verified when the flag is off, and an existing store is
> untouched.

Run the tests and confirm they fail for the right reasons (the request stays pending when
approval is off, and the declared response fields do not match the body).

### Step 2.2 — Verification response contract

In `apps/accounts/serializers.py`:

```python
class VerificationRequestResponseSerializer(VerificationRequestSerializer):
    """201 body: the request fields plus the submission envelope."""

    message = serializers.CharField(read_only=True)
    request_id = serializers.IntegerField(read_only=True)
```

In `apps/accounts/views.py`:

- Import `timezone` and `notify_verification_approved`.
- Replace the `@extend_schema(responses={201: VerificationRequestSerializer})` with
  `VerificationRequestResponseSerializer`.
- Replace the body after `serializer.save(...)`:

```python
from apps.admin_panel.models import PlatformConfig

config = PlatformConfig.get()

if config.vendor_approval_required:
    notify_admins_verification_request.delay(
        verification_request.id, request.user.email
    )
else:
    verification_request.status = VerificationRequest.Status.APPROVED
    verification_request.reviewed_at = timezone.now()
    verification_request.admin_notes = (
        "Auto-approved because vendor approval is disabled."
    )
    verification_request.save(
        update_fields=["status", "reviewed_at", "admin_notes"]
    )

    request.user.is_verified = True
    request.user.save(update_fields=["is_verified"])

    store = getattr(request.user, "store", None)
    if store is not None:
        store.is_verified = True
        store.save(update_fields=["is_verified"])

    notify_verification_approved(request.user)

track_verification_submitted(
    request.user, verification_request.company_name
)

payload = VerificationRequestSerializer(
    verification_request, context={"request": request}
).data
payload["message"] = "Verification request submitted successfully"
payload["request_id"] = verification_request.id
return Response(payload, status=status.HTTP_201_CREATED)
```

### Step 2.3 — Onboarding store creation

`SellerOnboardingStep1Serializer.save`:

```python
from apps.admin_panel.models import PlatformConfig

store, created = Store.objects.update_or_create(
    user=user,
    defaults={...},
)

if created and not PlatformConfig.get().vendor_approval_required:
    store.is_verified = True
    store.save(update_fields=["is_verified"])

return store
```

Existing stores are deliberately untouched on re-submission.

### Step 2.4 — Gate and commit

```powershell
python -m pytest tests/test_vendor_approval.py -q
python -m pytest -q
python manage.py makemigrations --check --dry-run
python -m flake8 apps hb --select=F401,F821,F841 --exclude=migrations
python manage.py spectacular --file schema.yml --validate
```

Commit:

```text
feat(accounts): honour vendor approval and fix the verification response

Auto-approves service-provider verification when vendor approval is
disabled, verifies newly created stores in that mode, and makes the 201
verification body match its declared schema. The store backfill already
ships in migration 0009, so no runtime command is added.
```

---

## Task 3 — Checkout delivery fee, delivery snapshot and invoice wording

**Why:** Checkout hardcodes `delivery_fee = 0.00`, never writes the delivery snapshot, and the
invoice prints an always-zero "Escrow Fee" while omitting the seller commission. Buyers must pay
the seller's configured delivery rate, and the invoice must show the real money split.

### Files

| Action | Path |
|---|---|
| Create | `apps/commerce/services/delivery.py` |
| Create | `apps/commerce/services/invoice.py` |
| Edit | `apps/commerce/views.py` (`CheckoutView`, `OrderInvoicePDFView`) |
| Create | `tests/test_checkout_delivery.py` |
| Create | `tests/test_invoice.py` |

### Step 3.1 — Write the failing tests

Create `tests/test_checkout_delivery.py`:

```python
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.accounts.models import DeliveryDetail
from apps.commerce.models import Order
from apps.listings.models import Listing
from apps.store.models import ShippingProfile

from .factories import (
    CartFactory,
    CartItemFactory,
    ListingFactory,
    StoreFactory,
    UserFactory,
)


def _profile(store, *, zone="Lagos", cost="150.00", threshold=None):
    return ShippingProfile.objects.create(
        store=store,
        zone_name=zone,
        carrier_name="Harbour Logistics",
        delivery_time_min=1,
        delivery_time_max=3,
        flat_rate_cost=Decimal(cost),
        free_shipping_threshold=(
            Decimal(threshold) if threshold is not None else None
        ),
        is_active=True,
    )


def _checkout_setup(listing, *, city="Lagos", state="Lagos", quantity=1):
    buyer = UserFactory()
    detail = DeliveryDetail.objects.create(
        user=buyer,
        contact_person="Ada Obi",
        country="Nigeria",
        address="12 Marina Road",
        state=state,
        city=city,
        phone="08030000000",
    )
    cart = CartFactory(buyer=buyer)
    item = CartItemFactory(
        cart=cart,
        listing=listing,
        store=listing.store,
        quantity=quantity,
        unit_price=listing.price,
        delivery_detail=detail,
    )
    return buyer, cart, item


def _post_checkout(client, cart):
    with patch("apps.commerce.views.initialize_transaction") as gateway:
        gateway.return_value = {
            "authorization_url": "https://pay.test/checkout",
            "access_code": "ac_test",
        }
        return client.post(
            "/commerce/checkout/",
            {
                "cart_item_ids": [cart.items.first().pk],
                "terms_accepted": True,
            },
            format="json",
        )


@pytest.mark.django_db
def test_city_match_charges_the_zone_rate_once_per_line(auth_client):
    store = StoreFactory()
    _profile(store, zone="Lagos", cost="150.00")
    listing = ListingFactory(store=store, price=Decimal("1000.00"))
    buyer, cart, _ = _checkout_setup(listing, quantity=2)

    response = _post_checkout(auth_client(buyer), cart)

    assert response.status_code == 201
    order = Order.objects.get(buyer=buyer)
    assert order.subtotal == Decimal("2000.00")
    assert order.delivery_fee == Decimal("150.00")
    assert order.total_amount == Decimal("2150.00")


@pytest.mark.django_db
def test_free_shipping_threshold_zeroes_the_fee(auth_client):
    store = StoreFactory()
    _profile(store, zone="Lagos", cost="150.00", threshold="2000.00")
    listing = ListingFactory(store=store, price=Decimal("2500.00"))
    buyer, cart, _ = _checkout_setup(listing)

    response = _post_checkout(auth_client(buyer), cart)

    assert response.status_code == 201
    order = Order.objects.get(buyer=buyer)
    assert order.delivery_fee == Decimal("0.00")
    assert order.total_amount == Decimal("2500.00")


@pytest.mark.django_db
def test_no_matching_zone_charges_zero(auth_client):
    store = StoreFactory()
    _profile(store, zone="Abuja", cost="500.00")
    listing = ListingFactory(store=store, price=Decimal("1000.00"))
    buyer, cart, _ = _checkout_setup(listing, city="Lagos")

    response = _post_checkout(auth_client(buyer), cart)

    assert response.status_code == 201
    assert Order.objects.get(buyer=buyer).delivery_fee == Decimal("0.00")


@pytest.mark.django_db
def test_service_listings_are_never_charged_delivery(auth_client):
    store = StoreFactory()
    _profile(store, zone="Lagos", cost="150.00")
    listing = ListingFactory(
        store=store, price=Decimal("1000.00"), listing_type=Listing.Type.SERVICE
    )
    buyer, cart, _ = _checkout_setup(listing)

    response = _post_checkout(auth_client(buyer), cart)

    assert response.status_code == 201
    assert Order.objects.get(buyer=buyer).delivery_fee == Decimal("0.00")


@pytest.mark.django_db
def test_checkout_writes_the_delivery_snapshot(auth_client):
    store = StoreFactory()
    _profile(store, zone="Lagos", cost="150.00")
    listing = ListingFactory(store=store, price=Decimal("1000.00"))
    buyer, cart, _ = _checkout_setup(listing)

    response = _post_checkout(auth_client(buyer), cart)

    assert response.status_code == 201
    order = Order.objects.get(buyer=buyer)
    assert order.delivery_address == "12 Marina Road, Lagos, Lagos, Nigeria"
    assert order.delivery_contact_name == "Ada Obi"
    assert order.delivery_contact_phone == "08030000000"
```

Create `tests/test_invoice.py`:

```python
from decimal import Decimal

import pytest

from apps.commerce.services.invoice import invoice_summary_rows

from .factories import OrderFactory, UserFactory


@pytest.mark.django_db
def test_invoice_summary_uses_commission_not_escrow():
    order = OrderFactory(
        subtotal=Decimal("1000.00"),
        delivery_fee=Decimal("150.00"),
        total_amount=Decimal("1150.00"),
        commission_rate=Decimal("5.00"),
        commission_amount=Decimal("50.00"),
        escrow_fee=Decimal("0.00"),
    )

    rows = invoice_summary_rows(order)

    labels = [label for label, _ in rows]
    assert labels[0] == "Subtotal"
    assert labels[1] == "Delivery Fee"
    assert labels[2] == "Total Amount"
    assert not any("Escrow" in label for label in labels)
    values = dict(rows)
    assert values["Subtotal"] == "NGN 1,000.00"
    assert values["Delivery Fee"] == "NGN 150.00"
    assert values["Total Amount"] == "NGN 1,150.00"
    assert "Sales Commission (5.00%)" in labels[3]
    assert "NGN 50.00" in labels[3]
    assert "deducted from seller proceeds" in labels[3]


@pytest.mark.django_db
def test_invoice_pdf_renders(auth_client):
    order = OrderFactory(
        subtotal=Decimal("1000.00"),
        delivery_fee=Decimal("150.00"),
        total_amount=Decimal("1150.00"),
        commission_rate=Decimal("5.00"),
        commission_amount=Decimal("50.00"),
    )

    response = auth_client(order.buyer).get(
        f"/commerce/orders/{order.pk}/invoice/pdf/"
    )

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
```

Run both files; they must fail (`calculate_delivery_fee` missing, fees zero, snapshot empty).

### Step 3.2 — Implement `apps/commerce/services/delivery.py`

```python
"""Delivery fee resolution from a seller's active shipping profiles."""
from decimal import Decimal

from apps.financials.services import money
from apps.listings.models import Listing

ZERO = Decimal("0.00")


def _match_profile(profiles, address):
    """Match city, then state, then country; first hit wins."""
    for part in (address.city, address.state, address.country):
        needle = (part or "").strip().lower()
        if not needle:
            continue
        matches = [
            profile
            for profile in profiles
            if (profile.zone_name or "").strip().lower() == needle
        ]
        if matches:
            return sorted(
                matches, key=lambda profile: (profile.flat_rate_cost, profile.pk)
            )[0]
    return None


def calculate_delivery_fee(cart_item, subtotal_ngn):
    """Return the NGN delivery fee for one cart line.

    Rules: services and missing addresses are free; a matching active zone
    charges its flat rate once per line; no match is free; a reached
    free-shipping threshold is free.
    """
    listing = cart_item.listing
    if listing.listing_type == Listing.Type.SERVICE:
        return ZERO

    address = cart_item.delivery_detail
    if address is None:
        return ZERO

    profiles = list(listing.store.shipping_profiles.filter(is_active=True))
    profile = _match_profile(profiles, address)
    if profile is None:
        return ZERO

    threshold = profile.free_shipping_threshold
    if threshold is not None and subtotal_ngn >= threshold:
        return ZERO

    return money(profile.flat_rate_cost)
```

### Step 3.3 — Wire checkout

In `CheckoutView.post`, add the import at the top of the module:

```python
from apps.commerce.services.delivery import calculate_delivery_fee
```

Inside the pricing loop, replace `delivery_fee = Decimal("0.00")` with:

```python
delivery_fee = calculate_delivery_fee(item, subtotal)
```

In the order creation call, add:

```python
delivery_detail = item.delivery_detail
delivery_address = ""
delivery_contact_name = ""
delivery_contact_phone = ""
if delivery_detail is not None:
    delivery_address = ", ".join(
        part
        for part in (
            delivery_detail.address,
            delivery_detail.city,
            delivery_detail.state,
            delivery_detail.country,
        )
        if part
    )
    delivery_contact_name = delivery_detail.contact_person
    delivery_contact_phone = delivery_detail.phone
```

and pass `delivery_address=delivery_address`,
`delivery_contact_name=delivery_contact_name`,
`delivery_contact_phone=delivery_contact_phone` to `Order.objects.create`.

Commission stays on the goods subtotal: do not change `accrue_earning`. The existing code already
computes commission from `subtotal` and includes `delivery` in the seller's gross.

### Step 3.4 — Invoice helper and rendering

Create `apps/commerce/services/invoice.py`:

```python
"""Presentation-independent invoice rows."""
from decimal import Decimal


def invoice_summary_rows(order):
    """Return ``(label, value)`` pairs for the invoice summary.

    The first three rows are the buyer-facing table. The fourth row is the
    seller-side commission note rendered below the total.
    """
    currency = order.currency or "NGN"
    subtotal = order.subtotal or Decimal("0.00")
    delivery = order.delivery_fee or Decimal("0.00")
    total = order.total_amount or Decimal("0.00")
    rate = order.commission_rate or Decimal("0.00")
    commission = order.commission_amount or Decimal("0.00")

    return [
        ("Subtotal", f"{currency} {subtotal:,.2f}"),
        ("Delivery Fee", f"{currency} {delivery:,.2f}"),
        ("Total Amount", f"{currency} {total:,.2f}"),
        (
            f"Sales Commission ({rate}%): {currency} {commission:,.2f} "
            "(deducted from seller proceeds)",
            "",
        ),
    ]
```

In `OrderInvoicePDFView.get`, replace the whole `summary_data = [...]` block with:

```python
from .services.invoice import invoice_summary_rows

rows = invoice_summary_rows(order)
summary_data = []
for label, value in rows[:3]:
    if label == "Total Amount":
        summary_data.append([
            Paragraph(
                "<b>Total Amount:</b>",
                ParagraphStyle("TotalLabel", parent=header_style, fontSize=10),
            ),
            Paragraph(
                f"<b>{value}</b>",
                ParagraphStyle("TotalVal", parent=body_style, fontSize=10),
            ),
        ])
    else:
        summary_data.append([
            Paragraph(f"{label}:", header_style),
            Paragraph(value, body_style),
        ])
```

After `story.append(summary_table)`, add:

```python
story.append(Spacer(1, 6))
story.append(Paragraph(rows[3][0], body_style))
```

Delete every `Escrow Fee` reference from the invoice.

### Step 3.5 — Gate and commit

```powershell
python -m pytest tests/test_checkout_delivery.py tests/test_invoice.py tests/test_checkout.py -q
python -m pytest -q
python manage.py makemigrations --check --dry-run
python -m flake8 apps hb --select=F401,F821,F841 --exclude=migrations
python manage.py spectacular --file schema.yml --validate
```

Commit:

```text
feat(commerce): charge seller delivery rates and correct the invoice

Checkout now resolves the seller's active shipping zone from the saved
delivery address, charges the flat rate once per cart line, honours the
free-shipping threshold, and snapshots the address on the order. The
invoice drops the always-zero escrow line and shows the seller sales
commission instead.
```

---

## Task 4 — Payout and earning state machine, dispute lifecycle

**Why:** `VendorEarning.PROCESSING` is never written, `Dispute.REFUNDED` and
`Dispute.CANCELLED` are unreachable, and the dispute action cannot be closed by the buyer. These
are defined statuses with no path to them.

### Files

| Action | Path |
|---|---|
| Edit | `apps/financials/services.py` (`allocate_payout`, `settle_payout`) |
| Edit | `apps/commerce/services/refunds.py` (`finalize_refund`) |
| Edit | `apps/commerce/views.py` (`DisputeActionView`, new `DisputeCancelView`) |
| Edit | `apps/commerce/serializers.py` (`DisputeResolutionSerializer`) |
| Edit | `apps/commerce/urls.py` |
| Create | `tests/test_payout_state_machine.py` |
| Create | `tests/test_dispute_lifecycle.py` |

### Step 4.1 — Write the failing tests

Create `tests/test_payout_state_machine.py`:

```python
from decimal import Decimal

import pytest

from apps.financials.models import (
    Payout,
    PayoutAllocation,
    VendorEarning,
    VendorWallet,
)
from apps.financials.services import allocate_payout, fail_payout, settle_payout

from .factories import PayoutFactory, VendorEarningFactory


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
def test_allocate_reserves_earnings_as_processing():
    store = VendorEarningFactory().store
    earning = _released_earning(store)
    payout = PayoutFactory(
        store=store, vendor=store.user, amount=Decimal("500.00")
    )

    allocate_payout(payout)

    earning.refresh_from_db()
    assert earning.status == VendorEarning.Status.PROCESSING
    assert PayoutAllocation.objects.filter(payout=payout).count() == 1


@pytest.mark.django_db
def test_settle_resolves_a_processing_earning_to_paid_out():
    store = VendorEarningFactory().store
    earning = _released_earning(store)
    payout = PayoutFactory(
        store=store, vendor=store.user, amount=Decimal("950.00")
    )

    allocate_payout(payout)
    settle_payout(payout)

    earning.refresh_from_db()
    payout.refresh_from_db()
    assert payout.status == Payout.Status.PAID
    assert earning.status == VendorEarning.Status.PAID_OUT
    assert earning.paid_out_amount == Decimal("950.00")


@pytest.mark.django_db
def test_partial_settle_leaves_partially_released():
    store = VendorEarningFactory().store
    earning = _released_earning(store)
    payout = PayoutFactory(
        store=store, vendor=store.user, amount=Decimal("400.00")
    )

    allocate_payout(payout)
    settle_payout(payout)

    earning.refresh_from_db()
    assert earning.status == VendorEarning.Status.PARTIALLY_RELEASED
    assert earning.paid_out_amount == Decimal("400.00")


@pytest.mark.django_db
def test_failed_payout_unwinds_processing_to_available():
    store = VendorEarningFactory().store
    earning = _released_earning(store)
    wallet, _ = VendorWallet.objects.get_or_create(
        store=store, defaults={"user": store.user, "currency": "NGN"}
    )
    wallet.available_balance = Decimal("0.00")
    wallet.save(update_fields=["available_balance"])
    payout = PayoutFactory(
        store=store, vendor=store.user, amount=Decimal("200.00")
    )

    allocate_payout(payout)
    fail_payout(payout, "bank rejected")

    earning.refresh_from_db()
    wallet.refresh_from_db()
    assert earning.status == VendorEarning.Status.AVAILABLE
    assert wallet.available_balance == Decimal("200.00")
    assert not payout.allocations.exists()


@pytest.mark.django_db
def test_settled_earning_is_not_released_again():
    store = VendorEarningFactory().store
    earning = _released_earning(store)
    payout = PayoutFactory(
        store=store, vendor=store.user, amount=Decimal("950.00")
    )
    allocate_payout(payout)
    settle_payout(payout)

    from apps.financials.tasks import release_pending_earnings_task

    release_pending_earnings_task()

    earning.refresh_from_db()
    assert earning.status == VendorEarning.Status.PAID_OUT
```

`release_pending_earnings_task` lives in `apps.financials.tasks` and is a Celery
`@shared_task`, which is directly callable in tests.

Create `tests/test_dispute_lifecycle.py`:

```python
from decimal import Decimal

import pytest

from apps.commerce.models import (
    Dispute,
    Order,
    OrderActivity,
    Payment,
    Refund,
)
from apps.commerce.services.refunds import finalize_refund
from apps.financials.models import VendorEarning

from .factories import (
    DisputeFactory,
    OrderFactory,
    OrderItemFactory,
    PaymentFactory,
    UserFactory,
)


def _paid_order_with_earning():
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
    VendorEarning.objects.create(
        order=order,
        vendor=order.seller,
        store=order.store,
        earning_type="buy",
        gross_amount=Decimal("1000.00"),
        commission_rate=Decimal("0.00"),
        commission_amount=Decimal("0.00"),
        net_amount=Decimal("1000.00"),
        status=VendorEarning.Status.AVAILABLE,
        released_amount=Decimal("1000.00"),
    )
    return order, payment


@pytest.mark.django_db
def test_full_refund_moves_an_open_dispute_to_refunded():
    order, payment = _paid_order_with_earning()
    dispute = DisputeFactory(order=order, buyer=order.buyer)
    refund = Refund.objects.create(
        payment=payment,
        amount=Decimal("1000.00"),
        currency="NGN",
        reference="RF-DISPUTE-FULL",
        reason="Item not delivered",
    )

    finalize_refund(refund)

    dispute.refresh_from_db()
    assert dispute.status == Dispute.Status.REFUNDED
    assert dispute.resolved_at is not None
    assert "RF-DISPUTE-FULL" in dispute.resolution_notes


@pytest.mark.django_db
def test_partial_refund_leaves_the_dispute_untouched():
    order, payment = _paid_order_with_earning()
    dispute = DisputeFactory(order=order, buyer=order.buyer)
    refund = Refund.objects.create(
        payment=payment,
        amount=Decimal("400.00"),
        currency="NGN",
        reference="RF-DISPUTE-PARTIAL",
        reason="Partial damage",
    )

    finalize_refund(refund)

    dispute.refresh_from_db()
    assert dispute.status == Dispute.Status.OPEN


@pytest.mark.django_db
def test_buyer_can_cancel_an_open_dispute(auth_client):
    dispute = DisputeFactory()

    response = auth_client(dispute.buyer).post(
        f"/commerce/disputes/{dispute.pk}/cancel/",
        {"resolution_notes": "Resolved directly with the seller."},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["message"] == "Dispute cancelled successfully."
    dispute.refresh_from_db()
    assert dispute.status == Dispute.Status.CANCELLED
    assert dispute.resolved_at is not None
    assert dispute.resolution_notes == "Resolved directly with the seller."


@pytest.mark.django_db
def test_only_the_buyer_can_cancel(auth_client):
    dispute = DisputeFactory()
    other = UserFactory()

    response = auth_client(other).post(
        f"/commerce/disputes/{dispute.pk}/cancel/", {}, format="json"
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_a_resolved_dispute_cannot_be_cancelled(auth_client):
    dispute = DisputeFactory(status=Dispute.Status.RESOLVED)

    response = auth_client(dispute.buyer).post(
        f"/commerce/disputes/{dispute.pk}/cancel/", {}, format="json"
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_admin_can_cancel_a_dispute(auth_client):
    dispute = DisputeFactory()
    admin = UserFactory(role="admin", is_staff=True, is_superuser=True)

    response = auth_client(admin).post(
        f"/commerce/disputes/{dispute.pk}/action/",
        {"action": "cancel"},
        format="json",
    )

    assert response.status_code == 200
    dispute.refresh_from_db()
    assert dispute.status == Dispute.Status.CANCELLED
```

### Step 4.2 — Payout state transitions

`apps/financials/services.py`:

In `allocate_payout`, after `PayoutAllocation.objects.create(...)`:

```python
if earning.status in (
    VendorEarning.Status.AVAILABLE,
    VendorEarning.Status.PARTIALLY_RELEASED,
):
    earning.status = VendorEarning.Status.PROCESSING
    earning.save(update_fields=["status"])
```

The queryset filter already restricts to those two statuses, so the guard is just clarity.

In `settle_payout`, replace the status branch with:

```python
if earning.paid_out_amount >= earning.net_amount:
    earning.status = VendorEarning.Status.PAID_OUT
elif earning.status in (
    VendorEarning.Status.AVAILABLE,
    VendorEarning.Status.PARTIALLY_RELEASED,
    VendorEarning.Status.PROCESSING,
):
    earning.status = VendorEarning.Status.PARTIALLY_RELEASED
```

`fail_payout` is already correct; do not change it.

### Step 4.3 — Refund closes the dispute

`apps/commerce/services/refunds.py`, on the full-refund path after `order.save(...)` (that is,
below the `if not full_refund: continue` guard, so partial refunds never touch a dispute):

```python
from ..models import Dispute  # add to the existing model import

dispute = (
    Dispute.objects.select_for_update()
    .filter(order=order)
    .first()
)
if dispute is not None and dispute.status in (
    Dispute.Status.OPEN,
    Dispute.Status.UNDER_REVIEW,
):
    dispute.status = Dispute.Status.REFUNDED
    dispute.resolved_at = timezone.now()
    dispute.resolution_notes = (
        f"Refund {refund.reference} completed for {order.order_number}."
    )
    dispute.save(
        update_fields=["status", "resolved_at", "resolution_notes"]
    )
```

### Step 4.4 — Dispute cancel endpoint

`apps/commerce/serializers.py`:

```python
class DisputeResolutionSerializer(serializers.Serializer):
    """Admin-only: resolve, refund or cancel a dispute."""

    action = serializers.ChoiceField(choices=["resolve", "refund", "cancel"])
    resolution_notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if attrs["action"] in ("resolve", "refund") and not attrs.get(
            "resolution_notes"
        ):
            raise serializers.ValidationError(
                {"resolution_notes": ["This field is required."]}
            )
        return attrs


class DisputeCancelSerializer(serializers.Serializer):
    """Buyer-only: cancel an open dispute."""

    resolution_notes = serializers.CharField(required=False, allow_blank=True)
```

`apps/commerce/views.py`, new view:

```python
class DisputeCancelView(APIView):
    """Buyer cancels their own open or under-review dispute."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=DisputeCancelSerializer,
        responses={200: inline_serializer(
            name="DisputeCancelResponse",
            fields={"message": serializers.CharField()},
        )},
    )
    def post(self, request, pk):
        from apps.financials.models import VendorEarning

        dispute = get_object_or_404(Dispute, pk=pk)
        if dispute.buyer_id != request.user.id:
            return Response(
                {"error": "Only the buyer can cancel this dispute."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if dispute.status not in (
            Dispute.Status.OPEN,
            Dispute.Status.UNDER_REVIEW,
        ):
            return Response(
                {"error": "Only open or under-review disputes can be cancelled."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload = DisputeCancelSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        notes = payload.validated_data.get("resolution_notes", "")

        dispute.status = Dispute.Status.CANCELLED
        dispute.resolved_at = timezone.now()
        if notes:
            dispute.resolution_notes = notes
        dispute.save(
            update_fields=["status", "resolved_at", "resolution_notes"]
        )

        VendorEarning.objects.filter(order=dispute.order).update(
            is_disputed=False
        )
        OrderActivity.objects.create(
            order=dispute.order,
            event_type=OrderActivity.EventType.OTHER,
            message="Dispute cancelled by the buyer.",
        )
        return Response({"message": "Dispute cancelled successfully."})
```

`DisputeActionView`:

- `notes = serializer.validated_data.get("resolution_notes", "")`
- add branch before the final `else`:

```python
elif action == "cancel":
    if earning:
        earning.is_disputed = False
        earning.save(update_fields=["is_disputed"])
    dispute.status = Dispute.Status.CANCELLED
    message = "Dispute cancelled successfully."
```

- final save:

```python
dispute.resolution_notes = notes
dispute.resolved_at = timezone.now() if action in ("resolve", "cancel") else None
dispute.save(update_fields=["status", "resolution_notes", "resolved_at"])
```

`apps/commerce/urls.py`:

```python
path(
    "disputes/<int:pk>/cancel/",
    DisputeCancelView.as_view(),
    name="dispute-cancel",
),
```

and import `DisputeCancelView`.

### Step 4.5 — Gate and commit

```powershell
python -m pytest tests/test_payout_state_machine.py tests/test_dispute_lifecycle.py tests/test_payouts.py tests/test_refunds.py -q
python -m pytest -q
python manage.py makemigrations --check --dry-run
python -m flake8 apps hb --select=F401,F821,F841 --exclude=migrations
python manage.py spectacular --file schema.yml --validate
```

Commit:

```text
feat(financials,commerce): complete payout and dispute state machines

Payout allocation reserves earnings as PROCESSING and settlement resolves
them, failed payouts unwind them, full refunds close open disputes as
REFUNDED, and buyers can cancel their own open disputes. Admin dispute
actions accept cancel and only require notes for resolve and refund.
```

---

## Task 5 — Notifications: web push, preferences, SMS cleanup, wording, admin

**Why:** Push is a stub, preferences have no API, Twilio is an unused second SMS branch, and the
"escrow" wording no longer matches the product. Every declared channel must actually work or
report `skipped` with a real reason.

### Files

| Action | Path |
|---|---|
| Edit | `apps/notifications/models.py` (`PushSubscription`) |
| Edit | `apps/notifications/channels.py` (`send_push`, SMS cleanup) |
| Edit | `apps/notifications/serializers.py` |
| Edit | `apps/notifications/views.py` |
| Edit | `apps/notifications/urls.py` |
| Edit | `apps/notifications/utils.py` (wording) |
| Edit | `apps/notifications/admin.py` |
| Edit | `hb/settings.py` (VAPID_SUBJECT, remove Twilio) |
| Edit | `requirements.txt` (`pywebpush`) |
| Create | `tests/test_notification_channels.py` |
| Create | `tests/test_notification_preferences.py` |

### Step 5.1 — Write the failing tests

Create `tests/test_notification_channels.py`:

```python
import json
import sys
import types
from decimal import Decimal

import pytest

from apps.notifications import channels
from apps.notifications.models import (
    Notification,
    NotificationDelivery,
    PushSubscription,
)

from .factories import UserFactory


def _delivery(user, **kwargs):
    notification = Notification.objects.create(
        recipient=user,
        notification_type="order_paid",
        title="Order paid",
        message="Your payment was received.",
        action_url="/orders/1",
    )
    return NotificationDelivery.objects.create(
        notification=notification,
        recipient=user,
        event_key="order_paid",
        channel=NotificationDelivery.Channel.PUSH,
        **kwargs,
    )


@pytest.mark.django_db
def test_push_is_skipped_without_a_private_key(settings):
    settings.VAPID_PRIVATE_KEY = ""
    status, provider_id, error = channels.send_push(_delivery(UserFactory()))

    assert status == "skipped"
    assert error == "Push is not configured."


@pytest.mark.django_db
def test_push_is_skipped_without_subscriptions(settings):
    settings.VAPID_PRIVATE_KEY = "private"
    status, _, error = channels.send_push(_delivery(UserFactory()))

    assert status == "skipped"
    assert error == "No push subscription registered for this user."


@pytest.mark.django_db
def test_push_sends_to_every_active_subscription(settings, monkeypatch):
    settings.VAPID_PRIVATE_KEY = "private"
    settings.VAPID_SUBJECT = "mailto:test@example.com"
    user = UserFactory()
    PushSubscription.objects.create(
        user=user, endpoint="https://push.example/1",
        p256dh="key1", auth="auth1", is_active=True,
    )
    PushSubscription.objects.create(
        user=user, endpoint="https://push.example/2",
        p256dh="key2", auth="auth2", is_active=True,
    )

    calls = []

    def fake_webpush(subscription_info, data, **kwargs):
        calls.append((subscription_info, data, kwargs))

    monkeypatch.setitem(
        sys.modules,
        "pywebpush",
        types.SimpleNamespace(webpush=fake_webpush, WebPushException=Exception),
    )

    status, provider_id, error = channels.send_push(_delivery(user))

    assert status == "sent"
    assert len(calls) == 2
    payload = json.loads(calls[0][1])
    assert payload == {
        "title": "Order paid",
        "body": "Your payment was received.",
        "url": "/orders/1",
        "type": "order_paid",
    }
    assert calls[0][2]["vapid_claims"] == {"sub": "mailto:test@example.com"}


@pytest.mark.django_db
def test_push_deactivates_a_gone_subscription(settings, monkeypatch):
    settings.VAPID_PRIVATE_KEY = "private"
    user = UserFactory()
    subscription = PushSubscription.objects.create(
        user=user, endpoint="https://push.example/gone",
        p256dh="key", auth="auth", is_active=True,
    )

    class Gone(Exception):
        response = types.SimpleNamespace(status_code=410)

    def fake_webpush(*args, **kwargs):
        raise Gone("gone")

    monkeypatch.setitem(
        sys.modules,
        "pywebpush",
        types.SimpleNamespace(
            webpush=fake_webpush, WebPushException=Gone
        ),
    )

    status, _, error = channels.send_push(_delivery(user))

    subscription.refresh_from_db()
    assert subscription.is_active is False
    assert status == "failed"
    assert "gone" in error


@pytest.mark.django_db
def test_sms_uses_termii_only(settings):
    settings.SMS_PROVIDER = "twilio"
    user = UserFactory(phone="08030000000")
    status, _, error = channels.send_sms(_delivery(user))

    assert status == "skipped"
    assert error == "SMS provider is not configured."


@pytest.mark.django_db
def test_staff_webhook_is_skipped_without_a_url(settings):
    settings.OPS_WEBHOOK_URL = ""
    delivery = _delivery(UserFactory())
    delivery.channel = NotificationDelivery.Channel.STAFF_WEBHOOK

    status, _, error = channels.send_staff_webhook(delivery)

    assert status == "skipped"
    assert error == "OPS_WEBHOOK_URL is not configured."
```

> The SMS assertion depends on the phone check running before the provider check; keep that order.

Create `tests/test_notification_preferences.py`:

```python
import pytest

from apps.notifications.models import NotificationPreference, PushSubscription

from .factories import UserFactory


@pytest.mark.django_db
def test_get_preferences_creates_all_categories(auth_client):
    user = UserFactory()

    response = auth_client(user).get("/notifications/preferences/")

    assert response.status_code == 200
    assert [row["category"] for row in response.data] == [
        "transactional", "messages", "marketing"
    ]
    assert NotificationPreference.objects.filter(user=user).count() == 3
    first = response.data[0]
    assert first == {
        "category": "transactional",
        "in_app": True,
        "email": True,
        "sms": False,
        "push": True,
    }


@pytest.mark.django_db
def test_patch_can_disable_sms(auth_client):
    user = UserFactory()

    response = auth_client(user).patch(
        "/notifications/preferences/marketing/",
        {"sms": True},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["sms"] is True
    pref = NotificationPreference.objects.get(
        user=user, category="marketing"
    )
    assert pref.sms is True


@pytest.mark.django_db
def test_transactional_in_app_and_email_cannot_be_disabled(auth_client):
    user = UserFactory()

    response = auth_client(user).patch(
        "/notifications/preferences/transactional/",
        {"in_app": False},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["error"] == (
        "Transactional in-app and email notifications cannot be disabled."
    )


@pytest.mark.django_db
def test_push_subscription_upsert_and_delete(auth_client):
    user = UserFactory()
    client = auth_client(user)
    body = {
        "endpoint": "https://push.example/abc",
        "keys": {"p256dh": "key", "auth": "auth"},
        "user_agent": "pytest",
    }

    created = client.post(
        "/notifications/push/subscriptions/", body, format="json"
    )
    assert created.status_code == 201

    updated = client.post(
        "/notifications/push/subscriptions/", body, format="json"
    )
    assert updated.status_code == 200
    assert PushSubscription.objects.filter(user=user).count() == 1

    deleted = client.delete(
        f"/notifications/push/subscriptions/{created.data['id']}/"
    )
    assert deleted.status_code == 204
    assert PushSubscription.objects.filter(user=user).count() == 0


@pytest.mark.django_db
def test_push_subscription_cannot_be_stolen(auth_client):
    owner = UserFactory()
    attacker = UserFactory()
    PushSubscription.objects.create(
        user=owner, endpoint="https://push.example/owned",
        p256dh="key", auth="auth",
    )

    response = auth_client(attacker).post(
        "/notifications/push/subscriptions/",
        {
            "endpoint": "https://push.example/owned",
            "keys": {"p256dh": "key", "auth": "auth"},
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.data["error"] == (
        "This push subscription belongs to another account."
    )


@pytest.mark.django_db
def test_push_public_key_reports_configuration(auth_client, settings):
    settings.VAPID_PUBLIC_KEY = ""

    response = auth_client(UserFactory()).get(
        "/notifications/push/public-key/"
    )

    assert response.status_code == 200
    assert response.data == {"public_key": "", "configured": False}
```

### Step 5.2 — Model

`apps/notifications/models.py`:

```python
class PushSubscription(models.Model):
    """A browser push endpoint owned by one user."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="push_subscriptions",
    )
    endpoint = models.URLField(max_length=500, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    user_agent = models.CharField(max_length=300, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "push_subscriptions"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "is_active"])]

    def __str__(self):
        return f"{self.user_id} @ {self.endpoint[:40]}"
```

Generate and commit the migration with the task:

```powershell
python manage.py makemigrations notifications
```

### Step 5.3 — Channel adapters

`apps/notifications/channels.py`:

- Delete the entire Twilio branch from `send_sms`.
- Replace the `send_push` stub with the real adapter:

```python
def send_push(delivery):
    if not getattr(settings, "VAPID_PRIVATE_KEY", ""):
        return "skipped", "", "Push is not configured."

    from .models import PushSubscription

    subscriptions = list(
        PushSubscription.objects.filter(
            user=delivery.recipient, is_active=True
        )
    )
    if not subscriptions:
        return "skipped", "", (
            "No push subscription registered for this user."
        )

    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        return "skipped", "", "Push is not configured."

    import json

    notification = delivery.notification
    payload = json.dumps({
        "title": notification.title if notification else "",
        "body": notification.message if notification else "",
        "url": notification.action_url if notification else "",
        "type": delivery.event_key,
    })

    sent = 0
    last_error = ""
    for subscription in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {
                        "p256dh": subscription.p256dh,
                        "auth": subscription.auth,
                    },
                },
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": settings.VAPID_SUBJECT},
                timeout=10,
            )
            sent += 1
        except WebPushException as exc:
            last_error = str(exc)
            status_code = getattr(
                getattr(exc, "response", None), "status_code", None
            )
            if status_code in (404, 410):
                subscription.is_active = False
                subscription.save(
                    update_fields=["is_active", "updated_at"]
                )
        except Exception as exc:
            last_error = str(exc)

    if sent:
        return "sent", f"{sent} subscription(s)", ""
    return "failed", "", last_error or "All push subscriptions failed."
```

`send_push` must never raise `WebPushException`; the task's generic retry path stays for unexpected
programming errors only.

### Step 5.4 — Preferences and push endpoints

`apps/notifications/serializers.py` append:

```python
from .models import NotificationPreference, PushSubscription


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = ("category", "in_app", "email", "sms", "push")
        read_only_fields = ("category",)


class PushSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PushSubscription
        fields = (
            "id", "endpoint", "user_agent", "is_active",
            "created_at", "updated_at",
        )
        read_only_fields = fields
```

`apps/notifications/views.py` append:

```python
from .models import NotificationPreference, PushSubscription
from .serializers import (
    NotificationPreferenceSerializer, PushSubscriptionSerializer,
)

PREFERENCE_CATEGORIES = (
    NotificationPreference.Category.TRANSACTIONAL,
    NotificationPreference.Category.MESSAGES,
    NotificationPreference.Category.MARKETING,
)


class NotificationPreferenceListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={200: NotificationPreferenceSerializer(many=True)})
    def get(self, request):
        preferences = {}
        for category in PREFERENCE_CATEGORIES:
            preference, _ = NotificationPreference.objects.get_or_create(
                user=request.user, category=category
            )
            preferences[category] = preference
        ordered = [preferences[category] for category in PREFERENCE_CATEGORIES]
        return Response(
            NotificationPreferenceSerializer(ordered, many=True).data
        )


class NotificationPreferenceDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=NotificationPreferenceSerializer,
        responses={200: NotificationPreferenceSerializer},
    )
    def patch(self, request, category):
        if category not in PREFERENCE_CATEGORIES:
            return Response(
                {"error": "Unknown notification category."},
                status=status.HTTP_404_NOT_FOUND,
            )

        preference, _ = NotificationPreference.objects.get_or_create(
            user=request.user, category=category
        )

        for field in ("in_app", "email", "sms", "push"):
            if field not in request.data:
                continue
            value = request.data[field]
            if (
                category == NotificationPreference.Category.TRANSACTIONAL
                and field in ("in_app", "email")
                and value is False
            ):
                return Response(
                    {
                        "error": (
                            "Transactional in-app and email notifications "
                            "cannot be disabled."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            setattr(preference, field, bool(value))

        preference.save()
        return Response(
            NotificationPreferenceSerializer(preference).data
        )
```

Push views:

```python
class PushSubscriptionListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={200: PushSubscriptionSerializer(many=True)})
    def get(self, request):
        queryset = PushSubscription.objects.filter(user=request.user)
        return Response(PushSubscriptionSerializer(queryset, many=True).data)

    @extend_schema(
        request=inline_serializer(
            name="PushSubscriptionCreate",
            fields={
                "endpoint": serializers.URLField(),
                "keys": serializers.DictField(),
                "user_agent": serializers.CharField(required=False),
            },
        ),
        responses={201: PushSubscriptionSerializer},
    )
    def post(self, request):
        endpoint = (request.data.get("endpoint") or "").strip()
        keys = request.data.get("keys") or {}
        p256dh = (keys.get("p256dh") or "").strip()
        auth = (keys.get("auth") or "").strip()
        if not endpoint or not p256dh or not auth:
            return Response(
                {"error": "endpoint, keys.p256dh and keys.auth are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing = PushSubscription.objects.filter(endpoint=endpoint).first()
        if existing is not None and existing.user_id != request.user.id:
            return Response(
                {"error": "This push subscription belongs to another account."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if existing is None:
            subscription = PushSubscription.objects.create(
                user=request.user,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                user_agent=request.data.get("user_agent", ""),
            )
            return Response(
                PushSubscriptionSerializer(subscription).data,
                status=status.HTTP_201_CREATED,
            )

        existing.p256dh = p256dh
        existing.auth = auth
        existing.user_agent = request.data.get("user_agent", existing.user_agent)
        existing.is_active = True
        existing.save()
        return Response(PushSubscriptionSerializer(existing).data)


class PushSubscriptionDeleteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request, pk):
        deleted, _ = PushSubscription.objects.filter(
            pk=pk, user=request.user
        ).delete()
        if not deleted:
            return Response(
                {"error": "Push subscription not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class PushPublicKeyView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        responses={200: inline_serializer(
            name="PushPublicKeyResponse",
            fields={
                "public_key": serializers.CharField(),
                "configured": serializers.BooleanField(),
            },
        )}
    )
    def get(self, request):
        public_key = getattr(settings, "VAPID_PUBLIC_KEY", "")
        return Response({
            "public_key": public_key,
            "configured": bool(public_key),
        })
```

Add `from django.conf import settings` to the views imports if absent.

`apps/notifications/urls.py`:

```python
path("preferences/", NotificationPreferenceListView.as_view(),
     name="notification-preferences"),
path("preferences/<str:category>/",
     NotificationPreferenceDetailView.as_view(),
     name="notification-preference-detail"),
path("push/subscriptions/", PushSubscriptionListCreateView.as_view(),
     name="push-subscription-list"),
path("push/subscriptions/<int:pk>/", PushSubscriptionDeleteView.as_view(),
     name="push-subscription-delete"),
path("push/public-key/", PushPublicKeyView.as_view(),
     name="push-public-key"),
```

`preferences/` and `push/` are literal prefixes, so the existing `<int:pk>/`
notification-detail routes cannot shadow them; no reordering is required.

### Step 5.5 — Settings, wording, admin, dependency

`hb/settings.py`: `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY` already exist next to
`OPS_WEBHOOK_URL`; add only the subject:

```python
VAPID_SUBJECT = config(
    "VAPID_SUBJECT", default="mailto:support@harbourhubglobal.com"
)
```

Delete `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`. Grep the repo afterwards:
`Get-ChildItem apps,hb -Recurse -Filter *.py | Select-String TWILIO` must be empty.

`apps/notifications/utils.py`: replace `"Funds are held in escrow."` with
`"Payment received. Funds are held by Harbour Hub until the order is completed."`

`apps/notifications/admin.py`:

```python
from django.contrib import admin

from .models import (
    Notification, NotificationDelivery, NotificationPreference,
    PushSubscription,
)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "recipient", "notification_type", "title",
                    "is_read", "created_at")
    list_filter = ("notification_type", "is_read", "priority")
    search_fields = ("recipient__email", "title", "message")
    readonly_fields = ("created_at", "read_at")
    ordering = ("-created_at",)


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "category", "in_app", "email", "sms", "push")
    list_filter = ("category",)
    search_fields = ("user__email",)


@admin.register(NotificationDelivery)
class NotificationDeliveryAdmin(admin.ModelAdmin):
    list_display = ("id", "channel", "status", "recipient", "event_key",
                    "attempts", "created_at")
    list_filter = ("channel", "status")
    search_fields = ("recipient__email", "event_key", "error")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "endpoint", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("user__email", "endpoint")
    readonly_fields = ("created_at", "updated_at")
```

`requirements.txt`: add `pywebpush==2.0.3` below `redis`. Run `pip install pywebpush==2.0.3`.

### Step 5.6 — Gate and commit

```powershell
python manage.py makemigrations notifications
python -m pytest tests/test_notification_channels.py tests/test_notification_preferences.py -q
python -m pytest -q
python manage.py makemigrations --check --dry-run
python -m flake8 apps hb --select=F401,F821,F841 --exclude=migrations
python manage.py spectacular --file schema.yml --validate
```

Commit:

```text
feat(notifications): deliver web push, expose preferences, drop Twilio

Adds PushSubscription, a real VAPID push adapter that deactivates gone
endpoints, preference and subscription APIs, the public VAPID key
endpoint, and admin registrations. SMS is Termii-only and the escrow
wording now describes Harbour Hub holding funds.
```

---

## Task 6 — Social login hardening, admin coverage, real analytics export

**Why:** Google/Apple verification can be bypassed or is not tied to this app's client IDs, most
business models are missing from the Django admin, and the analytics export returns two fake rows.

### Files

| Action | Path |
|---|---|
| Edit | `apps/accounts/social_auth.py` |
| Edit | `hb/settings.py` (`GOOGLE_CLIENT_ID`, `APPLE_CLIENT_ID`) |
| Edit | `apps/admin_panel/views.py` (`AdminAnalyticsExportView`) |
| Create | `apps/commerce/admin.py` |
| Edit | `apps/financials/admin.py`, `apps/notifications/admin.py` (Task 5), `apps/support/admin.py`, `apps/compliance/admin.py`, `apps/messaging/admin.py`, `apps/accounts/admin.py`, `apps/admin_panel/admin.py`, `apps/listings/admin.py`, `apps/core/admin.py` |
| Create | `tests/test_social_auth.py` |
| Create | `tests/test_admin_coverage.py` |
| Create | `tests/test_analytics_export.py` |

### Step 6.1 — Write the failing tests

Create `tests/test_social_auth.py`:

```python
from unittest.mock import patch

import pytest

from apps.accounts import social_auth

from .factories import UserFactory


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def _google_payload(**overrides):
    payload = {
        "iss": "https://accounts.google.com",
        "aud": "google-client-id",
        "email": "new-google@example.com",
        "email_verified": "true",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_google_is_unavailable_when_unconfigured(client, settings):
    settings.GOOGLE_CLIENT_ID = ""

    response = client.post(
        "/auth/social/google/", {"id_token": "x"}, format="json"
    )

    assert response.status_code == 503
    assert response.data["error"] == "Google login is not configured."


@pytest.mark.django_db
def test_google_creates_a_verified_user(client, settings, monkeypatch):
    settings.GOOGLE_CLIENT_ID = "google-client-id"
    monkeypatch.setattr(
        social_auth.requests, "get",
        lambda *a, **k: _Response(_google_payload()),
    )

    response = client.post(
        "/auth/social/google/", {"id_token": "x"}, format="json"
    )

    assert response.status_code == 200
    assert response.data["user"]["email"] == "new-google@example.com"
    user = social_auth.User.objects.get(email="new-google@example.com")
    assert user.is_verified is True
    assert user.role == "buyer"


@pytest.mark.django_db
def test_google_rejects_a_foreign_audience(client, settings, monkeypatch):
    settings.GOOGLE_CLIENT_ID = "google-client-id"
    monkeypatch.setattr(
        social_auth.requests, "get",
        lambda *a, **k: _Response(_google_payload(aud="someone-else")),
    )

    response = client.post(
        "/auth/social/google/", {"id_token": "x"}, format="json"
    )

    assert response.status_code == 400
    assert response.data["error"] == "Invalid Google token."


@pytest.mark.django_db
def test_google_rejects_an_unverified_email(client, settings, monkeypatch):
    settings.GOOGLE_CLIENT_ID = "google-client-id"
    monkeypatch.setattr(
        social_auth.requests, "get",
        lambda *a, **k: _Response(_google_payload(email_verified="false")),
    )

    response = client.post(
        "/auth/social/google/", {"id_token": "x"}, format="json"
    )

    assert response.status_code == 400
    assert response.data["error"] == (
        "Google email address is not verified."
    )


@pytest.mark.django_db
def test_apple_is_unavailable_when_unconfigured(client, settings):
    settings.APPLE_CLIENT_ID = ""

    response = client.post(
        "/auth/social/apple/", {"id_token": "x"}, format="json"
    )

    assert response.status_code == 503
    assert response.data["error"] == "Apple login is not configured."


@pytest.mark.django_db
def test_apple_verifies_signature_and_claims(client, settings, monkeypatch):
    settings.APPLE_CLIENT_ID = "apple-client-id"
    monkeypatch.setattr(
        social_auth.requests, "get",
        lambda *a, **k: _Response({"keys": [{"kid": "kid-1"}]}),
    )
    monkeypatch.setattr(
        social_auth.jwt, "get_unverified_header", lambda token: {"kid": "kid-1"}
    )
    monkeypatch.setattr(
        social_auth.jwt, "decode",
        lambda *a, **k: {
            "iss": "https://appleid.apple.com",
            "aud": "apple-client-id",
            "email": "new-apple@example.com",
            "email_verified": "true",
        },
    )
    monkeypatch.setattr(
        "jwt.algorithms.RSAAlgorithm.from_jwk", lambda key: "public-key"
    )

    response = client.post(
        "/auth/social/apple/", {"id_token": "x"}, format="json"
    )

    assert response.status_code == 200
    assert response.data["user"]["email"] == "new-apple@example.com"
```

> Patching `jwt.algorithms.RSAAlgorithm.from_jwk` is required: without it the
> `from_jwk` call would reject the two-field JWK above. The test therefore exercises this
> repository's claim checks (issuer, audience, verified email, user creation), not PyJWT itself.
> Keep the `social_auth.jwt.decode` patch so no real key or network call is needed.

Create `tests/test_admin_coverage.py`:

```python
import pytest
from django.contrib import admin

from apps.accounts.models import (
    DeliveryDetail, PasswordResetToken, UserPreference, UserSession, UserTwoFactor,
    VerificationRequest,
)
from apps.admin_panel.models import (
    AdminProfile, JobListing, PlatformConfig, RolePermission,
)
from apps.commerce.models import (
    Cart, CartItem, CheckoutSession, Dispute, Order, OrderActivity, OrderItem,
    Payment, QuoteRequest, Refund, RentalExtension, WebhookEvent,
)
from apps.compliance.models import ComplianceDocument
from apps.core.models import Feedback
from apps.financials.models import (
    BankAccount, Payout, PayoutAllocation, VendorEarning, VendorWallet,
    WalletTransaction,
)
from apps.listings.models import SavedItem
from apps.messaging.models import Conversation, Message
from apps.notifications.models import (
    Notification, NotificationDelivery, NotificationPreference, PushSubscription,
)
from apps.support.models import SupportTicket

MODELS = [
    Order, OrderItem, OrderActivity, CheckoutSession, Payment, Cart, CartItem,
    QuoteRequest, RentalExtension, WebhookEvent, Refund, Dispute,
    BankAccount, VendorEarning, Payout, VendorWallet, WalletTransaction,
    PayoutAllocation,
    Notification, NotificationPreference, NotificationDelivery, PushSubscription,
    SupportTicket, ComplianceDocument, Conversation, Message,
    PasswordResetToken, VerificationRequest, DeliveryDetail, UserPreference,
    UserTwoFactor, UserSession,
    RolePermission, AdminProfile, PlatformConfig, JobListing,
    SavedItem, Feedback,
]


@pytest.mark.parametrize("model", MODELS, ids=lambda model: model.__name__)
def test_model_is_registered_in_the_admin(model):
    assert admin.site.is_registered(model)
```

Create `tests/test_analytics_export.py`:

```python
import csv
import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.commerce.models import Dispute, Order
from apps.inquiries.models import Inquiry
from apps.listings.models import Listing

from .factories import (
    DisputeFactory,
    ListingFactory,
    OrderFactory,
    UserFactory,
)


def _admin():
    return UserFactory(role="admin", is_staff=True, is_superuser=True)


def _read_csv(response):
    return list(csv.DictReader(io.StringIO(response.content.decode())))


@pytest.mark.django_db
def test_export_returns_real_metrics(auth_client):
    OrderFactory(
        status=Order.Status.FULFILLED,
        total_amount=Decimal("1500.00"),
        placed_at=timezone.now(),
    )
    DisputeFactory(status=Dispute.Status.OPEN)
    listing = ListingFactory(
        status=Listing.Status.PUBLISHED, published_at=timezone.now()
    )
    Inquiry.objects.create(
        listing=listing,
        from_user=UserFactory(),
        to_user=listing.user,
        subject="Availability",
        message="Is this available?",
        contact_name="Ada Obi",
        contact_email="ada@example.com",
    )
    UserFactory()

    response = auth_client(_admin()).get("/admin-panel/analytics/export/")

    assert response.status_code == 200
    rows = {row["Metric"]: row["Value"] for row in _read_csv(response)}
    assert Decimal(rows["Total Revenue"]) == Decimal("1500.00")
    assert int(rows["Paid Orders"]) >= 1
    assert int(rows["Active Disputes"]) >= 1
    assert int(rows["New Inquiries"]) >= 1
    assert int(rows["New Users"]) >= 1
    assert int(rows["Active Listings"]) >= 1


@pytest.mark.django_db
def test_export_rejects_an_invalid_date(auth_client):
    response = auth_client(_admin()).get(
        "/admin-panel/analytics/export/?date_from=not-a-date"
    )

    assert response.status_code == 400
    assert response.data["error"] == "Invalid date format. Use YYYY-MM-DD."
```

### Step 6.2 — Harden social login

`hb/settings.py`, next to the other third-party credentials:

```python
GOOGLE_CLIENT_ID = config("GOOGLE_CLIENT_ID", default="")
APPLE_CLIENT_ID = config("APPLE_CLIENT_ID", default="")
```

Both default to empty, so an unconfigured environment returns `503` rather than crashing.

`apps/accounts/social_auth.py`:

```python
def verify_google_token(id_token=None, access_token=None):
    """Return {"payload": dict|None, "error": str|None}."""
    client_id = getattr(settings, "GOOGLE_CLIENT_ID", "")
    if not client_id:
        return {"payload": None, "error": "Google login is not configured."}

    if id_token:
        url = f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}"
    elif access_token:
        url = (
            "https://oauth2.googleapis.com/tokeninfo?access_token="
            f"{access_token}"
        )
    else:
        return {
            "payload": None,
            "error": "Either id_token or access_token is required.",
        }

    try:
        response = requests.get(url, timeout=5)
    except Exception as exc:
        logger.warning("Google token verification failed: %s", exc)
        return {"payload": None, "error": "Could not verify the Google token."}

    if response.status_code != 200:
        return {"payload": None, "error": "Invalid Google token."}

    payload = response.json()
    if payload.get("aud") != client_id:
        return {"payload": None, "error": "Invalid Google token."}
    if payload.get("iss") not in (
        "accounts.google.com", "https://accounts.google.com"
    ):
        return {"payload": None, "error": "Invalid Google token."}
    if payload.get("email_verified") not in (True, "true"):
        return {
            "payload": None,
            "error": "Google email address is not verified.",
        }
    if not payload.get("email"):
        return {
            "payload": None,
            "error": "Google token does not contain an email address.",
        }
    return {"payload": payload, "error": None}
```

Apple: remove the DEBUG bypass entirely and verify against JWKS with audience and issuer:

```python
def verify_apple_token(id_token):
    client_id = getattr(settings, "APPLE_CLIENT_ID", "")
    if not client_id:
        return {"payload": None, "error": "Apple login is not configured."}
    try:
        jwks_data = requests.get(
            "https://appleid.apple.com/auth/keys", timeout=5
        ).json()
        header = jwt.get_unverified_header(id_token)
        kid = header.get("kid")
        public_key = None
        for key in jwks_data.get("keys", []):
            if key.get("kid") == kid:
                from jwt.algorithms import RSAAlgorithm
                public_key = RSAAlgorithm.from_jwk(key)
                break
        if public_key is None:
            return {"payload": None, "error": "Invalid Apple token."}
        payload = jwt.decode(
            id_token,
            public_key,
            algorithms=["RS256"],
            audience=client_id,
            issuer="https://appleid.apple.com",
        )
        if payload.get("email_verified") not in (True, "true"):
            return {
                "payload": None,
                "error": "Apple email address is not verified.",
            }
        if not payload.get("email"):
            return {
                "payload": None,
                "error": "Apple token does not contain an email address.",
            }
        return {"payload": payload, "error": None}
    except Exception as exc:
        logger.warning("Verified Apple token decode failed: %s", exc)
        return {"payload": None, "error": "Invalid Apple token."}
```

`create_or_login_social_user(email, email_verified=False)`: pass
`is_verified=bool(email_verified)` on create. Existing users are not modified.

Both views:

```python
result = verify_google_token(id_token=id_token, access_token=access_token)
if result["error"] == "Google login is not configured.":
    return Response({"error": result["error"]},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE)
if result["payload"] is None:
    return Response({"error": result["error"]},
                    status=status.HTTP_400_BAD_REQUEST)

payload = result["payload"]
email = payload["email"]
user = create_or_login_social_user(
    email, email_verified=payload.get("email_verified") in (True, "true")
)
```

Do the same for Apple with `"Apple login is not configured."`.

Update both `@extend_schema` response bodies to declare `access`, `refresh` and
`user` (`id`, `email`, `role`) and add the 503 response.

### Step 6.3 — Admin registrations

Create `apps/commerce/admin.py` and fill the empty admin modules. A compact, explicit pattern:

```python
from django.contrib import admin

from .models import Order

READONLY = ("created_at", "updated_at")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "order_number", "buyer", "seller", "status",
                    "total_amount", "currency", "created_at")
    list_filter = ("status", "currency", "created_at")
    search_fields = ("order_number", "buyer__email", "seller__email")
    readonly_fields = ("order_number", "created_at", "updated_at")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
```

Register the remaining models with the same shape. Minimum fields per model:

| Model | `list_display` | `list_filter` | `search_fields` |
|---|---|---|---|
| `OrderItem` | id, order, listing, purchase_type, quantity, unit_price | purchase_type | order__order_number |
| `OrderActivity` | id, order, event_type, created_at | event_type | order__order_number |
| `CheckoutSession` | id, buyer, total_amount, currency, status, created_at | status | buyer__email |
| `Payment` | id, reference, buyer, amount, status, created_at | status, currency | reference, buyer__email |
| `Cart` | id, buyer, created_at | — | buyer__email |
| `CartItem` | id, cart, listing, quantity, unit_price | purchase_type | listing__title |
| `QuoteRequest` | id, listing, buyer, store, status, created_at | status | listing__title, buyer__email |
| `RentalExtension` | id, order_item, status, created_at | status | order_item__order__order_number |
| `WebhookEvent` | id, event_type, gateway_event_id, status, created_at | status, provider | gateway_event_id, event_type |
| `Refund` | id, reference, payment, amount, status, created_at | status | reference, payment__reference |
| `Dispute` | id, order, buyer, status, created_at | status | order__order_number, buyer__email |

`OrderActivity` and `WebhookEvent` are read-only: `readonly_fields` includes every field and
`has_add_permission`/`has_change_permission` return `False`.

`financials/admin.py`: `BankAccount` (`bank_name`, `account_name`, masked number in
`list_display`; never show the full number), `VendorEarning`, `Payout`, `VendorWallet`,
`WalletTransaction`, `PayoutAllocation`.

`notifications/admin.py`: already written in Task 5.

`support/admin.py`: `SupportTicket`; `compliance/admin.py`: `ComplianceDocument`;
`messaging/admin.py`: `Conversation`, `Message`.

`accounts/admin.py`: add `PasswordResetToken` (read-only), `VerificationRequest`,
`DeliveryDetail`, `UserPreference`, `UserTwoFactor`, `UserSession`.

`admin_panel/admin.py`: add `RolePermission`, `AdminProfile`, `PlatformConfig`, `JobListing`.

`listings/admin.py`: add `SavedItem`. `core/admin.py`: add `Feedback`.

For every `CharField` holding a token, password or full bank number, set the field to
`readonly_fields` and display a masked value via a method. Example:

```python
@admin.display(description="Account number")
def masked_account_number(self, obj):
    number = obj.account_number or ""
    return f"****{number[-4:]}" if number else ""
```

### Step 6.4 — Real analytics export

Replace `AdminAnalyticsExportView.get`:

```python
def get(self, request):
    import csv
    from datetime import date

    from django.http import HttpResponse

    from apps.accounts.models import User
    from apps.commerce.constants import SALES_STATUSES
    from apps.commerce.models import Dispute, Order
    from apps.inquiries.models import Inquiry
    from apps.listings.models import Listing

    def parse(value):
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    raw_from = request.query_params.get("date_from")
    raw_to = request.query_params.get("date_to")
    date_from = parse(raw_from)
    date_to = parse(raw_to)
    if (raw_from and date_from is None) or (raw_to and date_to is None):
        return Response(
            {"error": "Invalid date format. Use YYYY-MM-DD."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    orders = Order.objects.filter(status__in=SALES_STATUSES)
    disputes = Dispute.objects.filter(
        status__in=(Dispute.Status.OPEN, Dispute.Status.UNDER_REVIEW)
    )
    inquiries = Inquiry.objects.all()
    users = User.objects.all()
    listings = Listing.objects.filter(status=Listing.Status.PUBLISHED)

    if date_from:
        orders = orders.filter(placed_at__date__gte=date_from)
        disputes = disputes.filter(created_at__date__gte=date_from)
        inquiries = inquiries.filter(created_at__date__gte=date_from)
        users = users.filter(date_joined__date__gte=date_from)
        listings = listings.filter(created_at__date__gte=date_from)
    if date_to:
        orders = orders.filter(placed_at__date__lte=date_to)
        disputes = disputes.filter(created_at__date__lte=date_to)
        inquiries = inquiries.filter(created_at__date__lte=date_to)
        users = users.filter(date_joined__date__lte=date_to)
        listings = listings.filter(created_at__date__lte=date_to)

    period = f"{raw_from or 'beginning'} to {raw_to or 'now'}"
    rows = [
        ("Total Revenue", f"{orders.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00'):.2f}"),
        ("Paid Orders", orders.count()),
        ("Active Disputes", disputes.count()),
        ("New Inquiries", inquiries.count()),
        ("New Users", users.count()),
        ("Active Listings", listings.count()),
    ]

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="analytics_export_{raw_from or "all"}_'
        f'to_{raw_to or "now"}.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(["Metric", "Value", "Period"])
    for label, value in rows:
        writer.writerow([label, value, period])
    return response
```

Add `from decimal import Decimal` and `from django.db.models import Sum` at the top of the view
module if absent. Do not mutate any Orders; the export is read-only.

### Step 6.5 — Gate and commit

```powershell
python -m pytest tests/test_social_auth.py tests/test_admin_coverage.py tests/test_analytics_export.py -q
python -m pytest -q
python manage.py makemigrations --check --dry-run
python -m flake8 apps hb --select=F401,F821,F841 --exclude=migrations
python manage.py spectacular --file schema.yml --validate
```

Commit:

```text
feat(accounts,admin): harden social login, cover the admin, export real metrics

Google and Apple logins now require this app's client ID, a valid issuer,
a verified email and (for Apple) a real JWKS signature. Every business
model is registered in the Django admin with masked secrets and read-only
audit rows. The analytics export computes real aggregates in the requested
date range instead of returning placeholders.
```

---

## Task 7 — Routes, webhook alias, session device type, response-field correctness

**Why:** The canonical webhook path is missing, analytics is only reachable under a doubled
prefix, `device_type` is always blank, and several serializers declare fields the view never
returns (or omit fields the client needs).

### Files

| Action | Path |
|---|---|
| Edit | `apps/commerce/webhooks.py`, `apps/commerce/urls.py` |
| Create | `apps/analytics/canonical_urls.py`; edit `hb/api_urls_v1.py` |
| Edit | `apps/admin_panel/models.py` (`AdminActionLog.Meta.ordering`) |
| Edit | `apps/financials/serializers.py`, `apps/financials/views.py` |
| Edit | `apps/commerce/views.py` (quote messages) |
| Edit | `apps/commerce/serializers.py` (`OrderSerializer`) |
| Edit | `apps/accounts/views.py`, `apps/accounts/serializers.py` (`device_type`) |
| Edit | `apps/accounts/serializers.py` (remove stale TODO) |
| Create | `tests/test_routes.py` |
| Create | `tests/test_sessions.py` |
| Create | `tests/test_order_contract.py` |
| Create | `tests/test_financial_contract.py` |

### Step 7.1 — Write the failing tests

Create `tests/test_routes.py`:

```python
import pytest
from django.urls import resolve

from apps.commerce.webhooks import (
    PaystackWebhookLegacyView,
    PaystackWebhookView,
)

from .factories import UserFactory


@pytest.mark.django_db
def test_canonical_and_legacy_webhook_paths_share_the_view():
    canonical = resolve("/commerce/webhooks/paystack/")
    legacy = resolve("/commerce/payment/webhook/")

    assert canonical.func.view_class is PaystackWebhookView
    assert legacy.func.view_class is PaystackWebhookLegacyView
    assert issubclass(legacy.func.view_class, PaystackWebhookView)


@pytest.mark.django_db
def test_canonical_analytics_path_works(auth_client):
    admin_user = UserFactory(role="admin", is_staff=True)
    response = auth_client(admin_user).get("/analytics/")

    assert response.status_code == 200


@pytest.mark.django_db
def test_legacy_analytics_path_still_works(auth_client):
    admin_user = UserFactory(role="admin", is_staff=True)
    response = auth_client(admin_user).get("/analytics/analytics/")

    assert response.status_code == 200


@pytest.mark.django_db
def test_quote_paths_are_unchanged(auth_client):
    user = UserFactory()

    assert auth_client(user).get("/quotes/sent/").status_code == 200
    assert auth_client(user).get("/quotes/received/").status_code == 200
    assert auth_client(user).get("/commerce/quotes/sent/").status_code == 200
```

`/analytics/` is the canonical list route; `/analytics/analytics/` stays as the deprecated
doubled prefix. `AnalyticsViewSet` is admin-only (`IsAdminUser`), so both tests use a staff
admin user.

Create `tests/test_sessions.py`:

```python
import pytest

from apps.accounts.models import UserSession

from .factories import UserFactory


def _login(client, user, user_agent):
    return client.post(
        "/auth/login/",
        {"email": user.email, "password": "TestPass123!"},
        format="json",
        HTTP_USER_AGENT=user_agent,
    )


@pytest.mark.django_db
def test_login_records_device_type(client):
    user = UserFactory()
    user.set_password("TestPass123!")
    user.save(update_fields=["password"])

    response = _login(client, user, "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)")

    assert response.status_code == 200
    session = UserSession.objects.get(user=user)
    assert session.device_type == "mobile"


@pytest.mark.django_db
def test_login_records_desktop_device_type(client):
    user = UserFactory()
    user.set_password("TestPass123!")
    user.save(update_fields=["password"])

    _login(client, user, "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")

    assert UserSession.objects.get(user=user).device_type == "desktop"


@pytest.mark.django_db
def test_session_serializer_derives_a_missing_device_type(auth_client):
    user = UserFactory()
    session = UserSession.objects.create(
        user=user,
        device_name="Old session",
        device_type="",
        user_agent="Mozilla/5.0 (iPad; CPU OS 17_0)",
        token_jti="jti-derived",
    )

    response = auth_client(user).get("/auth/sessions/")

    assert response.status_code == 200
    row = next(item for item in response.data if item["id"] == session.pk)
    assert row["device_type"] == "tablet"
```

Create `tests/test_order_contract.py`:

```python
import pytest

from apps.commerce.models import Order
from apps.commerce.serializers import OrderSerializer

from .factories import OrderFactory, OrderItemFactory


@pytest.mark.django_db
def test_order_serializer_exposes_commission_fields():
    order = OrderFactory(
        commission_rate="5.00",
        commission_amount="50.00",
        escrow_fee="0.00",
        status=Order.Status.PAID,
    )
    OrderItemFactory(order=order)

    data = OrderSerializer(order).data

    assert data["commission_rate"] == "5.00"
    assert data["commission_amount"] == "50.00"
    assert data["escrow_fee"] == "0.00"


@pytest.mark.django_db
def test_order_list_uses_integer_order_id_and_order_number(auth_client):
    order = OrderFactory()
    OrderItemFactory(order=order)

    response = auth_client(order.buyer).get("/commerce/orders/")

    assert response.status_code == 200
    row = response.data["results"][0]
    assert isinstance(row["order_id"], int)
    assert row["order_id"] == order.pk
    assert row["order_number"] == order.order_number
```

Create `tests/test_financial_contract.py`:

```python
from decimal import Decimal

import pytest

from apps.financials.models import VendorWallet
from apps.financials.serializers import EarningsSummarySerializer

from .factories import StoreFactory


@pytest.mark.django_db
def test_earnings_summary_declares_only_returned_fields(auth_client):
    store = StoreFactory()
    wallet, _ = VendorWallet.objects.get_or_create(
        store=store,
        defaults={"user": store.user, "currency": "NGN"},
    )
    wallet.available_balance = Decimal("250.00")
    wallet.total_withdrawn = Decimal("100.00")
    wallet.save(update_fields=["available_balance", "total_withdrawn"])

    response = auth_client(store.user).get("/financials/earnings/summary/")

    assert response.status_code == 200
    assert set(response.data) == {
        "total_revenue",
        "pending_balance",
        "available_balance",
        "total_withdrawn",
        "revenue_change_percent",
        "currency",
    }
    declared = set(EarningsSummarySerializer().fields)
    assert declared == set(response.data)


@pytest.mark.django_db
def test_quote_action_messages_are_grammatical(auth_client):
    from apps.commerce.models import QuoteRequest

    from .factories import QuoteRequestFactory

    quote = QuoteRequestFactory()
    response = auth_client(quote.buyer).post(
        f"/commerce/quotes/{quote.pk}/cancel/", {}, format="json"
    )

    assert response.status_code == 200
    assert response.data["message"] == "Quote cancelled successfully"
```

Run the tests; they must fail on the missing canonical route, blank `device_type`, missing
commission keys, the stale serializer fields, and `Quote canceled successfully`.

### Step 7.2 — Webhook paths and response schema

`apps/commerce/webhooks.py`, define the response map once and use it on both views:

```python
PAYSTACK_WEBHOOK_RESPONSES = {
    200: inline_serializer(
        name="PaystackWebhookResponse",
        fields={
            "status": serializers.CharField(),
            "detail": serializers.CharField(required=False),
        },
    ),
    400: inline_serializer(
        name="PaystackWebhookBadRequest",
        fields={"error": serializers.CharField()},
    ),
    401: inline_serializer(
        name="PaystackWebhookUnauthorized",
        fields={"error": serializers.CharField()},
    ),
    500: inline_serializer(
        name="PaystackWebhookServerError",
        fields={"error": serializers.CharField()},
    ),
}
```

Use `@extend_schema(request=None, responses=PAYSTACK_WEBHOOK_RESPONSES)` on
`PaystackWebhookView.post`, then add:

```python
class PaystackWebhookLegacyView(PaystackWebhookView):
    """Deprecated alias kept for existing Paystack dashboard configurations."""

    @extend_schema(
        request=None,
        responses=PAYSTACK_WEBHOOK_RESPONSES,
        deprecated=True,
    )
    def post(self, request):
        return super().post(request)
```

Do not rely on a class-level `@extend_schema`; drf-spectacular replaces the inherited method
context and would lose the response declarations.

`apps/commerce/urls.py`:

```python
from .webhooks import PaystackWebhookLegacyView, PaystackWebhookView

path(
    "webhooks/paystack/",
    PaystackWebhookView.as_view(),
    name="paystack-webhook",
),
path(  # deprecated alias
    "payment/webhook/",
    PaystackWebhookLegacyView.as_view(),
    name="paystack-webhook-legacy",
),
```

### Step 7.3 — Canonical analytics route

Create `apps/analytics/canonical_urls.py`:

```python
from rest_framework.routers import SimpleRouter

from .views import AnalyticsViewSet

router = SimpleRouter()
router.register(r"analytics", AnalyticsViewSet, basename="analytics")

urlpatterns = router.urls
```

`hb/api_urls_v1.py`:

```python
path("", include("apps.analytics.canonical_urls")),
path("analytics/", include("apps.analytics.urls")),  # legacy doubled prefix
```

The canonical include must come before the legacy one.

### Step 7.4 — Small response fixes

`apps/financials/serializers.py`:

```python
class EarningsSummarySerializer(CurrencyConverterMixin, serializers.Serializer):
    monetary_fields = [
        "total_revenue", "pending_balance", "available_balance",
        "total_withdrawn",
    ]

    total_revenue = serializers.DecimalField(max_digits=14, decimal_places=2)
    pending_balance = serializers.DecimalField(max_digits=14, decimal_places=2)
    available_balance = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_withdrawn = serializers.DecimalField(max_digits=14, decimal_places=2)
    revenue_change_percent = serializers.FloatField()
    currency = serializers.CharField()
```

`apps/financials/views.py` already returns exactly those keys. Delete
`pending_change_percent` and `total_paid_out` from the serializer only.

`apps/commerce/views.py`, `QuoteRequestActionView`:

```python
MESSAGES = {
    "cancel": "Quote cancelled successfully",
    "decline": "Quote declined successfully",
    "respond": "Quote responded successfully",
    "convert": "Quote converted successfully",
}
...
return Response({"message": MESSAGES[action]})
```

`apps/commerce/serializers.py` `OrderSerializer`:

```python
order_id = serializers.IntegerField(source="id", read_only=True)

monetary_fields = [
    "subtotal", "delivery_fee", "escrow_fee", "commission_amount",
    "total_amount",
]
```

Add `"order_id"`, `"commission_rate"` and `"commission_amount"` to `Meta.fields` and to
`read_only_fields`. `order_id` is the integer the orders page uses for detail fetches; `id`
stays for compatibility and `order_number` stays on the list. Leave `escrow_fee` present and
always `0.00` for compatibility.

`apps/admin_panel/models.py` `AdminActionLog.Meta`: add `ordering = ["-created_at"]`.

`apps/accounts/serializers.py`: delete the `# TODO: send email ...` comment in
`PasswordResetRequestSerializer.save`; the view already enqueues the task.

### Step 7.5 — Session device type

`apps/accounts/views.py`, `CustomTokenObtainPairView`:

```python
def _parse_device_type(self, ua_string: str) -> str:
    ua = ua_string.lower()
    if "ipad" in ua or "tablet" in ua:
        return "tablet"
    if "iphone" in ua or "android" in ua or "mobile" in ua:
        return "mobile"
    if ua:
        return "desktop"
    return ""
```

Pass `device_type=self._parse_device_type(ua_string)` in `UserSession.objects.create`.

`UserSessionSerializer`:

```python
device_type = serializers.SerializerMethodField()

def get_device_type(self, obj):
    if obj.device_type:
        return obj.device_type
    ua = (obj.user_agent or "").lower()
    if "ipad" in ua or "tablet" in ua:
        return "tablet"
    if "iphone" in ua or "android" in ua or "mobile" in ua:
        return "mobile"
    return "desktop" if ua else ""
```

`GET /auth/sessions/` stays an unpaginated array; do not add pagination.

### Step 7.6 — Gate and commit

```powershell
python -m pytest tests/test_routes.py tests/test_sessions.py tests/test_order_contract.py tests/test_financial_contract.py -q
python -m pytest -q
python manage.py makemigrations --check --dry-run
python -m flake8 apps hb --select=F401,F821,F841 --exclude=migrations
python manage.py spectacular --file schema.yml --validate
```

Commit:

```text
fix(commerce,accounts,financials): align routes and response contracts

Adds the canonical Paystack webhook path with a deprecated alias,
exposes /analytics/ directly, records and derives session device types,
adds order commission fields, removes undeclared earnings-summary
fields, and makes quote action messages grammatical.
```

---

## Task 8 — Configuration, dependencies, CI/deploy, documentation and completion record

**Why:** The code and the runtime configuration have drifted: duplicated requirements, a stray
`Twilio`/`Faker` dependency, a hardcoded deploy host, a CI that tests Python 3.11 while production
runs 3.12, and documentation that claims real-time notifications and omits whole features.

This task is broad but mechanical. Do not change application behaviour here.

### Files

| Action | Path |
|---|---|
| Create | `apps/commerce/management/commands/check_paystack_config.py` |
| Edit | `hb/settings.py` (`PAYSTACK_WEBHOOK_URL`) |
| Edit | `.env.example`, `.env.prod.example` |
| Rewrite | `requirements.txt`, `requirements-dev.txt` |
| Edit | `.github/workflows/ci.yml`, `.github/workflows/deploy.yml`, `build.sh` |
| Rewrite | `docs/figma-backend-gap-checklist.md` |
| Create | `docs/product/future-backlog.md`; delete `New_Feautures.docx` |
| Edit | `README.md`, `docs/README.md`, `docs/api/README.md`, `docs/api/messages.md`, `docs/api/examples.md`, `docs/data-model.md`, `docs/sample-data.md` |
| Regenerate | `schema.yml`, `docs/api/endpoints.md` |
| Create | `docs/superpowers/plans/P5-COMPLETE.md` |
| Create | `tests/test_check_paystack_config.py` |

### Step 8.1 — Paystack configuration command

Create `apps/commerce/management/commands/check_paystack_config.py`:

```python
import hashlib
import hmac
import json
import secrets
import urllib.error
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

EXPECTED_WEBHOOK = (
    "https://api.harbourhubglobal.com/commerce/webhooks/paystack/"
)


class Command(BaseCommand):
    help = "Validate Paystack live keys and the deployed webhook endpoint."

    def add_arguments(self, parser):
        parser.add_argument(
            "--send-signed-event",
            action="store_true",
            help="POST a signed, non-mutating charge.success event.",
        )

    def handle(self, *args, **options):
        secret = getattr(settings, "PAYSTACK_SECRET_KEY", "")
        public = getattr(settings, "PAYSTACK_PUBLIC_KEY", "")
        webhook = getattr(settings, "PAYSTACK_WEBHOOK_URL", "")

        problems = []
        if not secret.startswith("sk_live_"):
            problems.append("PAYSTACK_SECRET_KEY is not a live secret key.")
        if not public.startswith("pk_live_"):
            problems.append("PAYSTACK_PUBLIC_KEY is not a live public key.")
        if webhook != EXPECTED_WEBHOOK:
            problems.append(
                f"PAYSTACK_WEBHOOK_URL must be {EXPECTED_WEBHOOK}."
            )
        if problems:
            raise CommandError(" ".join(problems))

        self.stdout.write(self.style.SUCCESS(
            "Paystack keys and webhook URL look valid."
        ))
        if not options["send_signed_event"]:
            return

        unsigned = urllib.request.Request(
            webhook,
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(unsigned, timeout=15)
        except urllib.error.HTTPError as exc:
            if exc.code != 401:
                raise CommandError(
                    f"Unsigned probe returned {exc.code}, expected 401."
                )
        except Exception as exc:
            raise CommandError(f"Unsigned probe failed: {exc}")

        payload = {
            "event": "charge.success",
            "data": {
                "id": f"p5-self-test-{secrets.token_hex(8)}",
                "reference": f"P5-SELFTEST-{secrets.token_hex(6)}",
                "amount": 1,
                "status": "success",
            },
        }
        body = json.dumps(payload).encode("utf-8")
        signature = hmac.new(
            secret.encode("utf-8"), body, hashlib.sha512
        ).hexdigest()
        signed = urllib.request.Request(
            webhook,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "x-paystack-signature": signature,
            },
        )
        try:
            response = urllib.request.urlopen(signed, timeout=15)
        except urllib.error.HTTPError as exc:
            raise CommandError(
                f"Signed probe returned {exc.code}, expected 200."
            )
        except Exception as exc:
            raise CommandError(f"Signed probe failed: {exc}")

        if response.status != 200:
            raise CommandError(
                f"Signed probe returned {response.status}, expected 200."
            )
        self.stdout.write(self.style.SUCCESS(
            "Signed non-mutating webhook accepted."
        ))
```

`tests/test_check_paystack_config.py`:

```python
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


@pytest.mark.django_db
def test_rejects_test_keys(settings):
    settings.PAYSTACK_SECRET_KEY = "sk_test_x"
    settings.PAYSTACK_PUBLIC_KEY = "pk_test_x"
    settings.PAYSTACK_WEBHOOK_URL = (
        "https://api.harbourhubglobal.com/commerce/webhooks/paystack/"
    )

    with pytest.raises(CommandError):
        call_command("check_paystack_config")


@pytest.mark.django_db
def test_accepts_live_prefixes_without_sending(settings):
    settings.PAYSTACK_SECRET_KEY = "sk_live_x"
    settings.PAYSTACK_PUBLIC_KEY = "pk_live_x"
    settings.PAYSTACK_WEBHOOK_URL = (
        "https://api.harbourhubglobal.com/commerce/webhooks/paystack/"
    )

    call_command("check_paystack_config")
```

`hb/settings.py`, next to the other Paystack values:

```python
PAYSTACK_WEBHOOK_URL = config(
    "PAYSTACK_WEBHOOK_URL",
    default="https://api.harbourhubglobal.com/commerce/webhooks/paystack/",
)
```

### Step 8.2 — Environment files

Add the variables listed in spec §4.11 to **both** `.env.example` and `.env.prod.example`.
Remove the three `TWILIO_*` variables everywhere. In `.env.prod.example` set:

```dotenv
PAYSTACK_SECRET_KEY=sk_live_REPLACE_ME
PAYSTACK_PUBLIC_KEY=pk_live_REPLACE_ME
PAYSTACK_WEBHOOK_URL=https://api.harbourhubglobal.com/commerce/webhooks/paystack/
SMS_PROVIDER=termii
VAPID_SUBJECT=mailto:support@harbourhubglobal.com
```

Every documented variable must be read by `hb/settings.py`; every setting read by code must be
documented. Cross-check with:

```powershell
Get-ChildItem apps,hb -Recurse -Filter *.py | Select-String 'config\("'
```

### Step 8.3 — Requirements

`requirements.txt` (production only, no duplicates):

```text
Django==4.2.23
djangorestframework==3.16.1
djangorestframework-simplejwt==5.5.1
django-filter==25.1
django-cors-headers==4.7.0
drf-spectacular==0.28.0
django-mptt==0.18.0
django-js-asset==3.1.2
django-timezone-field==7.1
django-celery-beat==2.8.1
django-storages==1.14.6
boto3==1.40.22
Pillow==11.3.0
dj-database-url==3.0.1
psycopg2-binary==2.9.10
redis==6.4.0
django-redis==6.0.0
celery==5.5.3
gunicorn==23.0.0
python-decouple==3.8
sentry-sdk==2.35.2
django-ratelimit==4.1.0
requests==2.32.5
pyotp==2.9.0
qrcode[pil]==8.2
posthog==6.7.6
reportlab==4.2.5
pywebpush==2.0.3
```

`requirements-dev.txt`:

```text
-r requirements.txt
pytest==8.4.1
pytest-django==4.11.1
pytest-cov==6.2.1
factory-boy==3.3.3
black==25.1.0
flake8==7.3.0
isort==6.0.1
django-debug-toolbar==6.0.0
django-extensions==4.1
Faker==37.6.0
```

Install and freeze-check locally:

```powershell
pip install -r requirements-dev.txt
pip check
```

If a pin fails to install, update the pin to the version pip resolves and record it in the commit
body. Do not leave an unpinned package.

### Step 8.4 — CI and deploy

`.github/workflows/ci.yml`:

- `python-version: "3.12"`.
- Add `python manage.py check`.
- Flake8 covers tests too:
  `flake8 apps hb tests --select=F401,F821,F841 --exclude=migrations`.
- Keep `makemigrations --check`, `migrate`, `spectacular --validate`, `pytest -q`.
- Add `PAYSTACK_WEBHOOK_URL` and empty `VAPID_*`/`GOOGLE_CLIENT_ID`/`APPLE_CLIENT_ID` to `env`
  so settings import cleanly.

`.github/workflows/deploy.yml`:

```yaml
host: ${{ secrets.EC2_HOST }}
username: ${{ secrets.EC2_USER }}
script: |
  cd ${{ secrets.EC2_PATH }}
  ...
```

`build.sh`:

```bash
#!/usr/bin/env bash
set -o errexit

echo "Starting build process..."
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate --noinput
echo "Build complete!"
```

Remove `makemigrations` and `create_sample_data`.

### Step 8.5 — Documentation

Rewrite `docs/figma-backend-gap-checklist.md` as a coverage map. Keep the Figma file link and the
frame links that already exist; replace every stale status with what the code now does. Every row
must name the endpoint or model that covers it. Genuine gaps go under a short "Remaining backlog"
section with a reason.

Create `docs/product/future-backlog.md` from `New_Feautures.docx`. PowerShell has no
heredocs, so write this extractor to `$env:TEMP\opencode\extract_docx.py` and run it:

```python
import re
import zipfile

with zipfile.ZipFile("New_Feautures.docx") as archive:
    xml = archive.read("word/document.xml").decode("utf-8")

xml = xml.replace("</w:p>", "\n")
text = re.sub(r"<[^>]+>", "", xml)
text = re.sub(r"\n{3,}", "\n\n", text)
print(text)
```

```powershell
python "$env:TEMP\opencode\extract_docx.py"
```

Transcribe the output into Markdown under these headings: **Advertisements**, **Premium users**,
**Social login**, **Real-time chat**, each with *What the document asked for*, *Current state* and
*Why it is deferred*. Then `git rm New_Feautures.docx`.

Update:

- `README.md`: remove "Real-time notifications"; describe in-app, email, SMS (Termii), web push
  and staff webhook; list the new environment variables; link the P5 spec, plan, P5-COMPLETE and
  future backlog.
- `docs/README.md`: add the new documents to the index.
- `docs/api/README.md`: canonical routes first, deprecated aliases labelled.
- `docs/api/messages.md`: add every message introduced in Tasks 1–7, including
  `Buy listings are currently disabled.`, the approval error, the push errors, preference errors,
  `Dispute cancelled successfully.`, `Quote declined successfully`, and the social-login errors.
- `docs/api/examples.md`: add a platform-config example, a listing-approval example, a delivery-fee
  checkout example and a push-subscription example.
- `docs/data-model.md`: add `PushSubscription`, `PlatformConfig` (public fields), the payout and
  dispute transitions, `Order.commission_rate`/`commission_amount`, and the deprecation note for
  `escrow_fee`.
- `docs/sample-data.md`: update the sample flow to show the platform config, a verified store and
  an order with a delivery fee.

### Step 8.6 — Regenerate the schema and endpoint reference

```powershell
python manage.py spectacular --file schema.yml --validate
python scripts/generate_api_reference.py
```

Commit both generated files with the documentation. Confirm the schema now contains
`/platform-config/`, both webhook paths (legacy marked deprecated), `/analytics/` and
`/analytics/analytics/`, and the new notification paths.

### Step 8.7 — Completion record

Create `docs/superpowers/plans/P5-COMPLETE.md` with:

- The task table: task number, commit hash, focused test count, full-suite count, date.
- The exact gate results for Task 8.
- A "Verified in this repository" list (unit/integration coverage).
- A "Requires staging" list: real Paystack rental-extension, refund and transfer webhooks, real
  transfers, Termii SMS, real browser push, Celery Beat scheduling, production-volume admin
  payments, the P0 manual acceptance checklist.
- The Paystack cutover status (Task 9): pending, then done/failed with the evidence.
- A link to `docs/product/future-backlog.md`.

### Step 8.8 — Gate and commit

```powershell
python -m pytest tests/test_check_paystack_config.py -q
python -m pytest -q
python manage.py check
python manage.py makemigrations --check --dry-run
python -m flake8 apps hb tests --select=F401,F821,F841 --exclude=migrations
python manage.py spectacular --file schema.yml --validate
```

Commit:

```text
chore: align configuration, CI, deploy and documentation with the P5 design

Pins production and dev dependencies, adds the Paystack configuration
check, documents every environment variable, fixes the Python version and
deploy secrets, rewrites the Figma coverage map, transcribes the future
backlog, and records P5 completion with its staging-only gaps.
```

---

## Task 9 — Production Paystack cutover (operational, no repository commit)

**Precondition:** Task 8 is deployed to `api.harbourhubglobal.com` and the owner has confirmed.

### Step 9.1 — Read-only inspection

```powershell
ssh -v -i "C:\Users\DON COMPUTER\Documents\Works\harbourhub-key.pem" ubuntu@16.16.214.13
```

On the server:

```bash
cd /var/www/harbourhub
git rev-parse --short HEAD
systemctl status harbourhub-web harbourhub-worker harbourhub-beat nginx --no-pager
curl -I https://api.harbourhubglobal.com/api/docs/
sudo systemctl show harbourhub-web -p EnvironmentFiles
```

Confirm key prefixes without printing the values:

```bash
sudo grep -E '^PAYSTACK_(SECRET|PUBLIC)_KEY=' /path/to/env | \
  sed -E 's/=(.{0,7}).*/=\1***/'
```

Confirm the canonical webhook exists in the deployed code:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  https://api.harbourhubglobal.com/commerce/webhooks/paystack/ \
  -H 'Content-Type: application/json' -d '{}'
```

Expect `401`.

Read the production platform config (read-only) with
`python manage.py shell -c "from apps.admin_panel.models import PlatformConfig; print(PlatformConfig.get())"`
and record the five flags.

### Step 9.2 — Cutover (only after explicit confirmation)

1. Back up the environment file with a timestamp and `chmod 600`.
2. Replace `PAYSTACK_SECRET_KEY`, `PAYSTACK_PUBLIC_KEY` and `PAYSTACK_WEBHOOK_URL` atomically with
   the live values supplied through a secure channel. Never echo them.
3. Restart `harbourhub-web`, `harbourhub-worker`, `harbourhub-beat` and `nginx`.
4. Run `python manage.py check_paystack_config --send-signed-event`.
5. Hand off the dashboard step: the owner sets **Live Webhook URL** to
   `https://api.harbourhubglobal.com/commerce/webhooks/paystack/` and confirms it. SSH cannot do
   this.
6. After the first live charge, check
   `GET https://api.paystack.co/integration/webhooks/events?status=Delivered` and match the
   `orders`/`payments` rows.
7. Confirm service health and no new signature errors.

### Step 9.3 — Rollback

Restore the backed-up env file, restart the three services, restore the previous dashboard webhook
URL, and confirm health.

### Step 9.4 — Record

Append the outcome to `docs/superpowers/plans/P5-COMPLETE.md` and commit only the record:

```text
docs: record the production Paystack cutover
```

---

## Completion criteria

P5 is complete when all of the following are true:

1. Tasks 1–8 are committed, each with a passing gate.
2. `python -m pytest -q` is green, `makemigrations --check` is clean, `flake8` F-checks are clean,
   and `spectacular --validate` reports zero warnings.
3. Every `PlatformConfig` flag changes real behaviour and is covered by a test.
4. The answer to "does this field exist?" is yes for every declared serializer field.
5. All five notification channels return `sent` or `skipped` with a truthful reason; none raises.
6. Every business model is registered in the Django admin.
7. `docs/figma-backend-gap-checklist.md` contains no stale "Missing" claim.
8. `docs/product/future-backlog.md` exists and the `.docx` is gone.
9. `P5-COMPLETE.md` lists every remaining staging-only verification.
10. Task 9 is either done or explicitly blocked on owner-supplied live keys and dashboard access,
    and the record says which.


