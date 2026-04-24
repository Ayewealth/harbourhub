from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ReportedContentViewSet,
    VerificationAdminViewSet,
    AdminVendorListView,
    AdminVendorActionView,
    AdminListingListView,
    AdminListingActionView,
    AdminPaymentListView,
    AdminMarkPayoutPaidView,
)
from .dashboard_views import (
    RolesMatrixView,
    MeDashboardPermissionsView,
    InviteAdminView,
    DashboardAdminListView,
    DashboardAdminDetailView,
    AcceptAdminInviteView,
    PlatformConfigView,
    AdminUserEditView,
)

router = DefaultRouter()
router.register(r'reports', ReportedContentViewSet, basename='reports')
router.register(r'verifications', VerificationAdminViewSet,
                basename='admin-verifications')

urlpatterns = router.urls + [
    # Dashboard settings
    path('dashboard/matrix/', RolesMatrixView.as_view()),
    path('dashboard/me/permissions/', MeDashboardPermissionsView.as_view()),
    path('dashboard/invite/', InviteAdminView.as_view()),
    path('dashboard/accept-invite/', AcceptAdminInviteView.as_view()),
    path('dashboard/admins/', DashboardAdminListView.as_view()),
    path('dashboard/admins/<int:pk>/revoke/',
         DashboardAdminDetailView.as_view()),
    path('dashboard/admins/<int:pk>/edit/',
         AdminUserEditView.as_view()),

    # Platform config
    path('dashboard/config/', PlatformConfigView.as_view()),

    # Vendors
    path('vendors/', AdminVendorListView.as_view()),
    path('vendors/<int:pk>/<str:action>/',
         AdminVendorActionView.as_view()),

    # Listings
    path('listings/', AdminListingListView.as_view()),
    path('listings/<int:pk>/<str:action>/',
         AdminListingActionView.as_view()),

    # Payments
    path('payments/', AdminPaymentListView.as_view()),
    path('payments/payouts/<int:pk>/mark-paid/',
         AdminMarkPayoutPaidView.as_view()),
]
