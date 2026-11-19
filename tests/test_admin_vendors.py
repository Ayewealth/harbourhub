import pytest
from rest_framework import status

from apps.accounts.models import User, VerificationRequest
from apps.admin_panel.constants import AdminModule, StaffRole
from apps.admin_panel.models import AdminActionLog, AdminProfile, RolePermission
from tests.factories import StoreFactory, UserFactory


@pytest.fixture
def staff_client(auth_client, db):
    """Staff client that may manage vendor onboarding."""
    RolePermission.objects.update_or_create(
        role=StaffRole.OPERATIONS_ADMIN,
        module=AdminModule.VENDORS_ONBOARDING,
        defaults={"can_view": True, "can_manage": True},
    )
    staff = UserFactory(role=User.Role.BUYER)
    AdminProfile.objects.create(
        user=staff,
        staff_role=StaffRole.OPERATIONS_ADMIN,
        invite_status=AdminProfile.InviteStatus.ACTIVE,
    )
    return auth_client(staff)


@pytest.fixture
def suspended_vendor(db):
    seller = UserFactory(role=User.Role.SELLER, is_verified=False)
    store = StoreFactory(user=seller, is_active=False, is_verified=False)
    return store


@pytest.mark.django_db
def test_approving_a_suspended_vendor_reactivates_the_store(
    staff_client, suspended_vendor
):
    response = staff_client.post(
        f"/admin-panel/vendors/{suspended_vendor.id}/approve/", {}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["message"] == "Vendor approved successfully."

    suspended_vendor.refresh_from_db()
    assert suspended_vendor.is_active is True
    assert suspended_vendor.is_verified is True

    seller = User.objects.get(pk=suspended_vendor.user_id)
    assert seller.is_verified is True


@pytest.mark.django_db
def test_approving_works_without_a_verification_request(
    staff_client, suspended_vendor
):
    assert not VerificationRequest.objects.filter(
        user=suspended_vendor.user
    ).exists()

    response = staff_client.post(
        f"/admin-panel/vendors/{suspended_vendor.id}/approve/", {}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    suspended_vendor.refresh_from_db()
    assert suspended_vendor.is_active is True
    assert suspended_vendor.is_verified is True


@pytest.mark.django_db
def test_approving_marks_a_pending_verification_request_approved(
    staff_client, suspended_vendor
):
    verification = VerificationRequest.objects.create(
        user=suspended_vendor.user,
        status=VerificationRequest.Status.PENDING,
    )

    response = staff_client.post(
        f"/admin-panel/vendors/{suspended_vendor.id}/approve/",
        {"notes": "Documents match."},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    verification.refresh_from_db()
    assert verification.status == VerificationRequest.Status.APPROVED
    assert verification.admin_notes == "Documents match."


@pytest.mark.django_db
def test_resume_reactivates_without_changing_verification(
    staff_client, suspended_vendor
):
    response = staff_client.post(
        f"/admin-panel/vendors/{suspended_vendor.id}/resume/",
        {"reason": "Appeal upheld."},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["message"] == "Vendor resumed successfully."

    suspended_vendor.refresh_from_db()
    assert suspended_vendor.is_active is True
    assert suspended_vendor.is_verified is False


@pytest.mark.django_db
def test_resume_is_logged(staff_client, suspended_vendor):
    staff_client.post(
        f"/admin-panel/vendors/{suspended_vendor.id}/resume/", {}, format="json"
    )

    log = AdminActionLog.objects.filter(
        action_type=AdminActionLog.ActionType.USER_UNBANNED
    ).latest("id")
    assert suspended_vendor.name in log.description


@pytest.mark.django_db
def test_unknown_vendor_action_is_rejected(staff_client, suspended_vendor):
    response = staff_client.post(
        f"/admin-panel/vendors/{suspended_vendor.id}/archive/", {}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["error"] == "Invalid action."

    suspended_vendor.refresh_from_db()
    assert suspended_vendor.is_active is False
