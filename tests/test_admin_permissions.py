import pytest
from rest_framework import status

from apps.accounts.models import User
from apps.admin_panel.constants import AdminModule, StaffRole
from apps.admin_panel.models import AdminProfile, RolePermission
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
            RolePermission.objects.update_or_create(
                role=role,
                module=module,
                defaults={
                    "can_view": can_view,
                    "can_manage": can_manage,
                },
            )


@pytest.mark.django_db
def test_buyer_cannot_reach_admin_endpoint(auth_client):
    client = auth_client(UserFactory(role=User.Role.BUYER))

    response = client.get("/admin-panel/payments/")

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_active_admin_profile_can_view_but_not_manage(
    auth_client, role_permissions
):
    staff = UserFactory(role=User.Role.BUYER)
    AdminProfile.objects.create(
        user=staff,
        staff_role=StaffRole.READ_ONLY,
        invite_status=AdminProfile.InviteStatus.ACTIVE,
    )
    client = auth_client(staff)

    assert client.get("/admin-panel/activity/").status_code == status.HTTP_200_OK
    assert (
        client.post("/admin-panel/payments/payouts/1/mark-paid/").status_code
        == status.HTTP_403_FORBIDDEN
    )


@pytest.mark.django_db
def test_role_admin_without_profile_is_not_staff(auth_client):
    user = UserFactory(role=User.Role.ADMIN)
    client = auth_client(user)

    response = client.get("/admin-panel/payments/")

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_manage_permission_controls_write_actions(auth_client, role_permissions):
    staff = UserFactory(role=User.Role.BUYER)
    AdminProfile.objects.create(
        user=staff,
        staff_role=StaffRole.OPERATIONS_ADMIN,
        invite_status=AdminProfile.InviteStatus.ACTIVE,
    )
    client = auth_client(staff)

    # Operations admin may view listings but the finance write endpoint is closed.
    assert client.get("/admin-panel/listings/").status_code == status.HTTP_200_OK
    assert (
        client.post("/admin-panel/payments/payouts/1/mark-paid/").status_code
        == status.HTTP_403_FORBIDDEN
    )
