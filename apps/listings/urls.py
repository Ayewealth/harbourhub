# listings/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    BestReviewedListView,
    ListingViewSet,
    TopDealsListView,
)

router = DefaultRouter()
router.register(r"", ListingViewSet, basename="listing")

urlpatterns = [
    path("top-deals/", TopDealsListView.as_view(), name="listing-top-deals"),
    path(
        "best-reviewed/",
        BestReviewedListView.as_view(),
        name="listing-best-reviewed",
    ),
    path("", include(router.urls)),
]
