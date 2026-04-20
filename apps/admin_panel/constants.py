"""
Admin dashboard roles and modules (Harbour Hub settings UI).

Used for RolePermission rows and permission checks.
"""
from django.utils.translation import gettext_lazy as _
from django.db import models


class StaffRole(models.TextChoices):
    SUPER_ADMIN = "super_admin", _("Super Admin")
    OPERATIONS_ADMIN = "operations_admin", _("Operations admin")
    FINANCE_ADMIN = "finance_admin", _("Finance admin")
    SUPPORT_ADMIN = "support_admin", _("Support admin")
    COMPLIANCE_ADMIN = "compliance_admin", _("Compliance Admin")
    READ_ONLY = "read_only", _("Read only")


class AdminModule(models.TextChoices):
    OVERVIEW_DASHBOARD = "overview_dashboard", _("Overview Dashboard")
    LISTINGS_MANAGEMENT = "listings_management", _("Listings management")
    ORDERS_BOOKINGS = "orders_bookings", _("Orders & Bookings")
    VENDORS_ONBOARDING = "vendors_onboarding", _("Vendors & onboarding")
    PAYMENTS_FINANCE = "payments_finance", _("Payments & finance")
    COMPLIANCE_CONTRACTS = "compliance_contracts", _("Compliance & Contracts")
    SUPPORTS = "supports", _("Supports")
    ANALYTICS = "analytics", _("Analytics")


# Default matrix from product spec (VIEW / MANAGE per module per role).
# Tuple: (can_view, can_manage)
DEFAULT_ROLE_MATRIX: dict[str, dict[str, tuple[bool, bool]]] = {
    StaffRole.SUPER_ADMIN: {
        AdminModule.OVERVIEW_DASHBOARD: (True, True),
        AdminModule.LISTINGS_MANAGEMENT: (True, True),
        AdminModule.ORDERS_BOOKINGS: (True, True),
        AdminModule.VENDORS_ONBOARDING: (True, True),
        AdminModule.PAYMENTS_FINANCE: (True, False),  # VIEW only for payments
        AdminModule.COMPLIANCE_CONTRACTS: (True, True),
        AdminModule.SUPPORTS: (True, True),
        AdminModule.ANALYTICS: (True, True),
    },
    StaffRole.OPERATIONS_ADMIN: {
        AdminModule.OVERVIEW_DASHBOARD: (True, True),
        AdminModule.LISTINGS_MANAGEMENT: (True, True),
        AdminModule.ORDERS_BOOKINGS: (True, True),
        AdminModule.VENDORS_ONBOARDING: (True, False),
        AdminModule.PAYMENTS_FINANCE: (True, False),
        AdminModule.COMPLIANCE_CONTRACTS: (False, False),
        AdminModule.SUPPORTS: (True, False),
        AdminModule.ANALYTICS: (True, False),
    },
    StaffRole.FINANCE_ADMIN: {
        AdminModule.OVERVIEW_DASHBOARD: (True, True),
        AdminModule.LISTINGS_MANAGEMENT: (True, True),
        AdminModule.ORDERS_BOOKINGS: (False, False),
        AdminModule.VENDORS_ONBOARDING: (False, False),
        AdminModule.PAYMENTS_FINANCE: (True, True),
        AdminModule.COMPLIANCE_CONTRACTS: (True, True),
        AdminModule.SUPPORTS: (True, True),
        AdminModule.ANALYTICS: (True, True),
    },
    StaffRole.SUPPORT_ADMIN: {
        AdminModule.OVERVIEW_DASHBOARD: (True, True),
        AdminModule.LISTINGS_MANAGEMENT: (True, True),
        AdminModule.ORDERS_BOOKINGS: (True, True),
        AdminModule.VENDORS_ONBOARDING: (True, True),
        AdminModule.PAYMENTS_FINANCE: (True, False),
        AdminModule.COMPLIANCE_CONTRACTS: (False, False),
        AdminModule.SUPPORTS: (True, True),
        AdminModule.ANALYTICS: (True, True),
    },
    StaffRole.COMPLIANCE_ADMIN: {
        AdminModule.OVERVIEW_DASHBOARD: (True, True),
        AdminModule.LISTINGS_MANAGEMENT: (True, True),
        AdminModule.ORDERS_BOOKINGS: (True, True),
        AdminModule.VENDORS_ONBOARDING: (True, True),
        AdminModule.PAYMENTS_FINANCE: (True, False),
        AdminModule.COMPLIANCE_CONTRACTS: (True, True),
        AdminModule.SUPPORTS: (True, True),
        AdminModule.ANALYTICS: (True, True),
    },
    StaffRole.READ_ONLY: {
        AdminModule.OVERVIEW_DASHBOARD: (True, True),
        AdminModule.LISTINGS_MANAGEMENT: (False, False),
        AdminModule.ORDERS_BOOKINGS: (False, False),
        AdminModule.VENDORS_ONBOARDING: (False, False),
        AdminModule.PAYMENTS_FINANCE: (False, False),
        AdminModule.COMPLIANCE_CONTRACTS: (False, False),
        AdminModule.SUPPORTS: (False, False),
        AdminModule.ANALYTICS: (False, False),
    },
}
