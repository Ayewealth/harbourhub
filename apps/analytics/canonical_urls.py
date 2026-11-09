from rest_framework.routers import SimpleRouter

from .views import AnalyticsViewSet

router = SimpleRouter()
router.register(r"analytics", AnalyticsViewSet, basename="analytics")

urlpatterns = router.urls
