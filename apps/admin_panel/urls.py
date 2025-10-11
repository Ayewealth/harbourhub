# apps/admin_panel/urls.py
from rest_framework.routers import DefaultRouter
from .views import ReportedContentViewSet, VerificationAdminViewSet

router = DefaultRouter()
router.register(r'reports', ReportedContentViewSet, basename='reports')
router.register(r'verifications', VerificationAdminViewSet,
                basename='admin-verifications')

urlpatterns = router.urls
