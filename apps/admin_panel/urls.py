from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import ReportedContentViewSet, VerificationAdminViewSet
from .dashboard_views import (
    RolesMatrixView,
    MeDashboardPermissionsView,
    InviteAdminView,
    DashboardAdminListView,
    DashboardAdminDetailView,
    AcceptAdminInviteView,
)

router = DefaultRouter()
router.register(r'reports', ReportedContentViewSet, basename='reports')
router.register(r'verifications', VerificationAdminViewSet,
                basename='admin-verifications')

urlpatterns = router.urls + [
    # Roles matrix
    path('dashboard/matrix/', RolesMatrixView.as_view(), name='dashboard-matrix'),

    # Current admin's own permissions
    path('dashboard/me/permissions/', MeDashboardPermissionsView.as_view(),
         name='dashboard-me-permissions'),

    # Invite a new or existing user as admin
    path('dashboard/invite/', InviteAdminView.as_view(), name='dashboard-invite'),

    # Accept invite and set password
    path('dashboard/accept-invite/', AcceptAdminInviteView.as_view(),
         name='dashboard-accept-invite'),

    # List all dashboard admins
    path('dashboard/admins/', DashboardAdminListView.as_view(),
         name='dashboard-admins'),

    # Revoke a specific admin's access
    path('dashboard/admins/<int:pk>/revoke/',
         DashboardAdminDetailView.as_view(), name='dashboard-admin-revoke'),
]
