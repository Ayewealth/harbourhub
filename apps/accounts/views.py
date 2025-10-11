# accounts/views.py
from django.conf import settings
from django.utils.decorators import method_decorator
from rest_framework import status, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.mixins import CreateModelMixin, RetrieveModelMixin, UpdateModelMixin
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from rest_framework_simplejwt.views import TokenObtainPairView
from django_ratelimit.decorators import ratelimit
from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.views import APIView

from .serializers import (
    UserRegistrationSerializer, CustomTokenObtainPairSerializer,
    UserProfileSerializer, UserProfileUpdateSerializer,
    PasswordChangeSerializer, PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer, VerificationRequestSerializer
)
from .permissions import IsOwnerOrAdmin
from .models import VerificationRequest
from .emails import EmailService
from apps.accounts.tasks import send_welcome_email_task, send_password_reset_email_task, send_password_reset_confirmation_email_task, notify_admins_verification_request

User = get_user_model()


@extend_schema_view(
    create=extend_schema(
        summary="Register new user",
        description="Register a new user account with role selection"
    )
)
class UserRegistrationViewSet(CreateModelMixin, GenericViewSet):
    """User registration endpoint"""

    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]

    @method_decorator(ratelimit(key='ip', rate='5/h', method=['POST']))
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        user = serializer.save()
        send_welcome_email_task.delay(user.id)


class CustomTokenObtainPairView(TokenObtainPairView):
    """Custom JWT token view with user data"""

    serializer_class = CustomTokenObtainPairSerializer

    @method_decorator(ratelimit(key='ip', rate='10/h', method='POST'))
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


@extend_schema_view(
    retrieve=extend_schema(summary="Get user profile"),
    update=extend_schema(summary="Update user profile"),
    partial_update=extend_schema(summary="Partially update user profile"),
)
class UserProfileViewSet(RetrieveModelMixin, UpdateModelMixin, GenericViewSet):
    """Viewset for authenticated user profile."""

    queryset = User.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]

    def get_serializer_class(self):
        if self.action in ["update", "partial_update"]:
            return UserProfileUpdateSerializer
        return UserProfileSerializer

    def get_object(self):
        return self.request.user


class PasswordChangeView(APIView):
    """Endpoint for changing password when logged in."""
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=PasswordChangeSerializer, responses={200: dict})
    def post(self, request):
        serializer = PasswordChangeSerializer(
            data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"message": "Password changed successfully"}, status=status.HTTP_200_OK)


class PasswordResetRequestView(APIView):
    """Start password reset by email."""
    permission_classes = [permissions.AllowAny]

    @method_decorator(ratelimit(key="ip", rate="3/h", method="POST"))
    @extend_schema(request=PasswordResetRequestSerializer, responses={202: dict})
    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reset_token = serializer.save()

        response_data = {
            "message": "If an account with this email exists, a password reset email has been sent."
        }
        if reset_token:
            send_password_reset_email_task.delay(reset_token.id)
            if settings.DEBUG:
                # for dev/testing only
                response_data["reset_token"] = reset_token.token

        return Response(response_data, status=status.HTTP_202_ACCEPTED)


class PasswordResetConfirmView(APIView):
    """Confirm password reset using token."""
    permission_classes = [permissions.AllowAny]

    @extend_schema(request=PasswordResetConfirmSerializer, responses={200: dict})
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        send_password_reset_confirmation_email_task.delay(user.id)
        return Response({"message": "Password reset successfully"}, status=status.HTTP_200_OK)


class VerificationViewSet(viewsets.ViewSet):
    """Service provider verification workflow"""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Request verification",
        description="Submit verification request for service providers",
        request=VerificationRequestSerializer,
        responses={201: VerificationRequestSerializer}
    )
    @action(detail=False, methods=['post'], url_path='request')
    def request_verification(self, request):
        """Submit verification request"""
        if request.user.role != User.Role.SERVICE_PROVIDER:
            return Response({
                'error': 'Only service providers can request verification'
            }, status=status.HTTP_400_BAD_REQUEST)

        if request.user.is_verified:
            return Response({
                'error': 'User is already verified'
            }, status=status.HTTP_400_BAD_REQUEST)

        verification_request = VerificationRequest.objects.create(
            user=request.user,
            company_name=request.data.get('company_name', ''),
            business_license=request.data.get('business_license', ''),
            insurance_certificate=request.data.get(
                'insurance_certificate', ''),
            certifications=request.data.get('certifications', ''),
            references=request.data.get('references', ''),
            additional_info=request.data.get('additional_info', '')
        )

        # Notify admins asynchronously
        notify_admins_verification_request.delay(
            verification_request.id,
            request.user.email
        )

        return Response({
            'message': 'Verification request submitted successfully',
            'request_id': verification_request.id
        }, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Get verification status",
        description="Get current verification status for user",
        responses={200: VerificationRequestSerializer}
    )
    @action(detail=False, methods=['get'], url_path='status')
    def status(self, request):
        """Get user's verification status"""
        if request.user.role != User.Role.SERVICE_PROVIDER:
            return Response({
                'error': 'Only service providers can check verification status'
            }, status=status.HTTP_400_BAD_REQUEST)

        verification_request = VerificationRequest.objects.filter(
            user=request.user
        ).order_by('-created_at').first()

        return Response({
            'is_verified': request.user.is_verified,
            'has_pending_request': bool(
                verification_request and verification_request.status == VerificationRequest.Status.PENDING
            ),
            'last_request': VerificationRequestSerializer(verification_request).data if verification_request else None
        })
