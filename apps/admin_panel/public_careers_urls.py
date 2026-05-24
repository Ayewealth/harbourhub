# apps/admin_panel/public_careers_urls.py
from django.urls import path
from .views import PublicJobListingViewSet

urlpatterns = [
    path("", PublicJobListingViewSet.as_view({'get': 'list'}), name="public-job-list"),
    path("<int:pk>/", PublicJobListingViewSet.as_view({'get': 'retrieve'}), name="public-job-detail"),
]
