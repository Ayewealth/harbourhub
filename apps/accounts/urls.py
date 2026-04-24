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
    UserPreferenceView,
    # 2FA
    TwoFactorStatusView,
    TwoFactorSetupView,
    TwoFactorQRCodeView,
    TwoFactorEnableView,
    TwoFactorDisableView,
    TwoFactorVerifyLoginView,
    # Sessions
    SessionListView,
    SessionRemoveView,
    SessionRemoveAllView,
    # Onboarding
    BecomeSellerView,
    SellerOnboardingStep1View,
    SellerOnboardingStep2View,
    SellerOnboardingStep3View,
    OnboardingStatusView,
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

    # 2FA
    path('2fa/status/', TwoFactorStatusView.as_view(),
         name='2fa-status'),
    path('2fa/setup/', TwoFactorSetupView.as_view(),
         name='2fa-setup'),
    path('2fa/qr/', TwoFactorQRCodeView.as_view(),
         name='2fa-qr'),
    path('2fa/enable/', TwoFactorEnableView.as_view(),
         name='2fa-enable'),
    path('2fa/disable/', TwoFactorDisableView.as_view(),
         name='2fa-disable'),
    path('2fa/verify/', TwoFactorVerifyLoginView.as_view(),
         name='2fa-verify-login'),

    # Sessions
    path('sessions/', SessionListView.as_view(),
         name='session-list'),
    path('sessions/<int:pk>/', SessionRemoveView.as_view(),
         name='session-remove'),
    path('sessions/remove-all/', SessionRemoveAllView.as_view(),
         name='session-remove-all'),

    # Seller onboarding
    path('become-seller/', BecomeSellerView.as_view(),
         name='become-seller'),
    path('onboarding/status/', OnboardingStatusView.as_view(),
         name='onboarding-status'),
    path('onboarding/step-1/', SellerOnboardingStep1View.as_view(),
         name='onboarding-step-1'),
    path('onboarding/step-2/', SellerOnboardingStep2View.as_view(),
         name='onboarding-step-2'),
    path('onboarding/step-3/', SellerOnboardingStep3View.as_view(),
         name='onboarding-step-3'),
]
