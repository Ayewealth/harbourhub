# accounts/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    UserRegistrationViewSet,
    CustomTokenObtainPairView,
    UserProfileViewSet,
    PasswordChangeView,
    PasswordResetRequestView,
    PasswordResetConfirmView,
    VerificationViewSet,
    OTPRequestView,
    OTPVerifyView,
    SetPasswordView,
    DeliveryDetailListCreateView,
    DeliveryDetailRetrieveUpdateDestroyView,
    DeliveryDetailSetDefaultView,
    UserPreferenceView
)

router = DefaultRouter()
router.register(r'register', UserRegistrationViewSet, basename='register')
router.register(r'profile', UserProfileViewSet, basename='profile')
router.register(r'verification', VerificationViewSet, basename='verification')

urlpatterns = [
    # JWT Authentication
    path("login/", CustomTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("otp/request/", OTPRequestView.as_view(), name="otp-request"),
    path("otp/verify/", OTPVerifyView.as_view(), name="otp-verify"),

    # Registration & profile
    path("", include(router.urls)),

    # Password management
    path("set-password/", SetPasswordView.as_view(), name="set-password"),
    path("password/change/", PasswordChangeView.as_view(), name="password_change"),
    path("password/reset/request/", PasswordResetRequestView.as_view(),
         name="password_reset_request"),
    path("password/reset/confirm/", PasswordResetConfirmView.as_view(),
         name="password_reset_confirm"),

    # Delivery details
    path('delivery-details/', DeliveryDetailListCreateView.as_view(),
         name='delivery-list-create'),
    path('delivery-details/<int:pk>/',
         DeliveryDetailRetrieveUpdateDestroyView.as_view(), name='delivery-detail'),
    path('delivery-details/<int:pk>/set-default/',
         DeliveryDetailSetDefaultView.as_view(), name='delivery-set-default'),

    # Account preferences
    path('preferences/', UserPreferenceView.as_view(), name='user-preferences'),
]
