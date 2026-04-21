# listings/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    BestReviewedListView,
    ListingViewSet,
    TopDealsListView,
    SavedItemListView,
    SavedItemToggleView,
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
    path("saved/", SavedItemListView.as_view(),
         name="saved-items"),              # ← add
    path("<int:pk>/save/", SavedItemToggleView.as_view(), name="listing-save"),
    path("", include(router.urls)),
]
