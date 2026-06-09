# categories/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter, SimpleRouter
from .views import CategoryViewSet, CategoryAdminViewSet

# Public (read-only)
public_router = DefaultRouter()
public_router.register(r'', CategoryViewSet, basename='category')

# Admin (CRUD)
admin_router = SimpleRouter()
admin_router.register(r'admin', CategoryAdminViewSet,
                      basename='category-admin')

urlpatterns = [
    # Admin endpoints: /categories/admin/ , /categories/admin/{id}/
    path('', include(admin_router.urls)),

    # Public endpoints: /categories/ , /categories/{id}/ , /categories/tree/
    path('', include(public_router.urls)),
]
