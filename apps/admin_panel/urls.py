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
    AdminActivityViewSet,
    AdminOrderViewSet,
    AdminPaymentStatsView,
    AdminReportStatsView,
    AdminAnalyticsExportView,
    AdminGlobalSearchView,
    AdminOrderTrackingView,
    AdminConversationListView,
    AdminConversationMessageHistoryView,
    AdminJobListingViewSet,
    AdminUserListView,
    AdminUserActionView,
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
router.register(r'activity', AdminActivityViewSet, basename='admin-activity')
router.register(r'orders', AdminOrderViewSet, basename='admin-orders')
router.register(r'careers', AdminJobListingViewSet, basename='admin-careers')

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
    path('payments/stats/', AdminPaymentStatsView.as_view()),
    path('payments/payouts/<int:pk>/mark-paid/',
         AdminMarkPayoutPaidView.as_view()),

    # Reports/Analytics
    path('reports/stats/', AdminReportStatsView.as_view()),
    path('analytics/export/', AdminAnalyticsExportView.as_view()),

    # Search
    path('search/', AdminGlobalSearchView.as_view()),

    # Order Tracking & Chat Monitoring
    path('orders/<str:pk_or_num>/tracking/', AdminOrderTrackingView.as_view(), name='admin-order-tracking'),
    path('conversations/', AdminConversationListView.as_view(), name='admin-conversations-list'),
    path('conversations/<int:pk>/messages/', AdminConversationMessageHistoryView.as_view(), name='admin-conversation-messages'),

    # Users
    path('users/', AdminUserListView.as_view(), name='admin-users-list'),
    path('users/<int:pk>/<str:action>/', AdminUserActionView.as_view(), name='admin-user-action'),
]
