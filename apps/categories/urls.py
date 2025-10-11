# categories/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CategoryViewSet, CategoryAdminViewSet

# Public (read-only)
public_router = DefaultRouter()
public_router.register(r'', CategoryViewSet, basename='category')

# Admin (CRUD)
admin_router = DefaultRouter()
admin_router.register(r'admin', CategoryAdminViewSet,
                      basename='category-admin')

urlpatterns = [
    # Public endpoints: /categories/ , /categories/{id}/ , /categories/tree/
    path('', include(public_router.urls)),

    # Admin endpoints: /categories/admin/ , /categories/admin/{id}/
    path('', include(admin_router.urls)),
]
