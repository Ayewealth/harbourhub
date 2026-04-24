import io
import qrcode
import qrcode.image.svg

from django.http import HttpResponse
from django.conf import settings
from django.utils.decorators import method_decorator
from rest_framework import status, permissions, viewsets, generics
from rest_framework.decorators import action
from rest_framework.mixins import CreateModelMixin, RetrieveModelMixin, UpdateModelMixin
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from rest_framework_simplejwt.views import TokenObtainPairView
from django_ratelimit.decorators import ratelimit
from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.views import APIView
from django.core.signing import TimestampSigner

from .serializers import (
    UserRegistrationSerializer, CustomTokenObtainPairSerializer,
    UserProfileSerializer, UserProfileUpdateSerializer,
    PasswordChangeSerializer, PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer, VerificationRequestSerializer,
    OTPRequestSerializer, OTPVerifySerializer,
    SetPasswordSerializer, DeliveryDetailSerializer,
    UserPreferenceSerializer,
    TwoFactorSetupSerializer,
    TwoFactorEnableSerializer,
    TwoFactorDisableSerializer,
    TwoFactorVerifyLoginSerializer,
    TwoFactorStatusSerializer,
    UserSessionSerializer,
    SellerOnboardingStep1Serializer,
    SellerOnboardingStep2Serializer,
    SellerOnboardingStep3Serializer,
    BecomeSellerSerializer,
)
from .permissions import IsOwnerOrAdmin
from .models import DeliveryDetail, UserPreference, VerificationRequest, OneTimePassword, UserTwoFactor, UserSession
from .emails import EmailService
from apps.accounts.tasks import send_welcome_email_task, send_password_reset_email_task, send_password_reset_confirmation_email_task, notify_admins_verification_request
from rest_framework_simplejwt.tokens import RefreshToken

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
    authentication_classes = []  # disable JWT parsing
    permission_classes = [permissions.AllowAny]

    @method_decorator(ratelimit(key='ip', rate='20/h', method=['POST']))
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        user = serializer.save()
        send_welcome_email_task.delay(user.id)


class OTPRequestView(APIView):
    """Request OTP for registration or login"""
    permission_classes = [permissions.AllowAny]
    serializer_class = OTPRequestSerializer()

    def post(self, request):
        serializer = OTPRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"message": "OTP sent successfully."}, status=status.HTTP_200_OK)


class OTPVerifyView(APIView):
    """Verify OTP for registration or login, auto-login if purpose=login"""
    permission_classes = [permissions.AllowAny]
    serializer_class = OTPVerifySerializer()

    def post(self, request):
        serializer = OTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        otp = serializer.save()

        # --- If it's for login, issue JWT immediately ---
        if otp.purpose == OneTimePassword.Purpose.LOGIN:
            try:
                user = User.objects.get(email__iexact=otp.email)
            except User.DoesNotExist:
                return Response({"error": "No account found for this email."}, status=status.HTTP_404_NOT_FOUND)

            if not user.is_active:
                return Response({"error": "User account is inactive."}, status=status.HTTP_403_FORBIDDEN)

            refresh = RefreshToken.for_user(user)
            return Response({
                "message": "OTP verified successfully. Login complete.",
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username,
                    "full_name": user.full_name,
                    "role": user.role,
                    "is_verified": user.is_verified,
                },
                "tokens": {
                    "refresh": str(refresh),
                    "access": str(refresh.access_token),
                }
            }, status=status.HTTP_200_OK)

        # --- For registration, just confirm success (they proceed to final step) ---
        return Response({
            "message": "OTP verified successfully. Proceed to complete registration."
        }, status=status.HTTP_200_OK)


class SetPasswordView(APIView):
    """Allow OTP-only users to set a password after account creation"""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SetPasswordSerializer()

    def post(self, request):
        serializer = SetPasswordSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {"message": "Password has been set successfully."},
            status=status.HTTP_200_OK,
        )


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

    @method_decorator(ratelimit(key='ip', rate='10/h', method='POST'))
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)

        if response.status_code == 200:
            # Check if user has 2FA enabled
            user_data = response.data.get('user', {})
            user_id = user_data.get('id')
            if user_id:
                try:
                    tf = UserTwoFactor.objects.get(
                        user_id=user_id, is_enabled=True)
                    # Return partial response — frontend must
                    # complete 2FA verification using the secure token
                    signer = TimestampSigner()
                    token = signer.sign(str(user_id))
                    return Response({
                        'requires_2fa': True,
                        'token': token,
                        'message': (
                            'Please complete 2FA verification.')
                    }, status=status.HTTP_200_OK)
                except UserTwoFactor.DoesNotExist:
                    pass

            # No 2FA — record session
            self._record_session(request, response.data)

        return response

    def _record_session(self, request, token_data):
        try:
            from rest_framework_simplejwt.tokens import (
                AccessToken)
            access = AccessToken(token_data['access'])
            jti = str(access.get('jti', ''))
            user_id = access.get('user_id')

            ua_string = request.META.get('HTTP_USER_AGENT', '')
            device_name = self._parse_device_name(ua_string)

            UserSession.objects.create(
                user_id=user_id,
                device_name=device_name,
                user_agent=ua_string,
                ip_address=self._get_ip(request),
                token_jti=jti,
            )
        except Exception:
            pass

    def _parse_device_name(self, ua_string: str) -> str:
        ua = ua_string.lower()
        if 'iphone' in ua:
            return 'iPhone'
        elif 'ipad' in ua:
            return 'iPad'
        elif 'android' in ua:
            return 'Android Device'
        elif 'windows' in ua:
            return 'Windows PC'
        elif 'mac' in ua:
            return 'Mac'
        elif 'linux' in ua:
            return 'Linux'
        return 'Unknown Device'

    def _get_ip(self, request) -> str:
        xff = request.META.get('HTTP_X_FORWARDED_FOR')
        if xff:
            return xff.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '')


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


class DeliveryDetailListCreateView(generics.ListCreateAPIView):
    serializer_class = DeliveryDetailSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return DeliveryDetail.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class DeliveryDetailRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = DeliveryDetailSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return DeliveryDetail.objects.filter(user=self.request.user)


class DeliveryDetailSetDefaultView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        detail = generics.get_object_or_404(
            DeliveryDetail, pk=pk, user=request.user
        )
        # Unset all others first
        DeliveryDetail.objects.filter(
            user=request.user, is_default=True
        ).exclude(pk=pk).update(is_default=False)

        detail.is_default = True
        detail.save(update_fields=['is_default'])

        return Response({'message': 'Default delivery address updated.'})


class UserPreferenceView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        prefs, _ = UserPreference.objects.get_or_create(user=request.user)
        serializer = UserPreferenceSerializer(prefs)
        return Response(serializer.data)

    def patch(self, request):
        prefs, _ = UserPreference.objects.get_or_create(user=request.user)
        serializer = UserPreferenceSerializer(
            prefs, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class TwoFactorStatusView(APIView):
    """Check if 2FA is enabled for the user."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        tf = UserTwoFactor.objects.filter(
            user=request.user).first()
        return Response({
            'is_enabled': tf.is_enabled if tf else False
        })


class TwoFactorSetupView(APIView):
    """
    Step 1: Get secret + QR URI to show in authenticator app.
    Does NOT enable 2FA yet — user must verify code first.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        tf = UserTwoFactor.get_or_create_secret(request.user)
        return Response({
            'secret': tf.secret,
            'qr_uri': tf.get_qr_uri(),
            'is_enabled': tf.is_enabled,
        })


class TwoFactorQRCodeView(APIView):
    """
    Returns QR code as SVG image.
    Frontend renders this as <img src="/api/v1/auth/2fa/qr/"> 
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        tf = UserTwoFactor.get_or_create_secret(request.user)
        uri = tf.get_qr_uri()

        # Generate SVG QR code
        img = qrcode.make(
            uri,
            image_factory=qrcode.image.svg.SvgImage
        )
        buffer = io.BytesIO()
        img.save(buffer)
        return HttpResponse(
            buffer.getvalue(),
            content_type='image/svg+xml'
        )


class TwoFactorEnableView(APIView):
    """
    Step 2: Submit TOTP code to enable 2FA.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = TwoFactorEnableSerializer(
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({
            'message': '2FA enabled successfully.'
        })


class TwoFactorDisableView(APIView):
    """Disable 2FA by verifying current TOTP code."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = TwoFactorDisableSerializer(
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({
            'message': '2FA disabled successfully.'
        })


class TwoFactorVerifyLoginView(APIView):
    """
    Called after normal login when user has 2FA enabled.
    Returns JWT tokens if code is valid.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = TwoFactorVerifyLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.get_user()

        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(user)
        return Response({
            'message': '2FA verified successfully.',
            'tokens': {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            },
            'user': {
                'id': user.id,
                'email': user.email,
                'role': user.role,
            }
        })


class SessionListView(APIView):
    """List all active sessions/devices for the user."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        sessions = UserSession.objects.filter(
            user=request.user,
            is_active=True
        )
        serializer = UserSessionSerializer(
            sessions,
            many=True,
            context={'request': request}
        )
        return Response(serializer.data)


class SessionRemoveView(APIView):
    """Remove/revoke a specific session."""
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, pk):
        try:
            session = UserSession.objects.get(
                pk=pk, user=request.user)
        except UserSession.DoesNotExist:
            return Response(
                {'error': 'Session not found.'},
                status=status.HTTP_404_NOT_FOUND
            )

        session.is_active = False
        session.save(update_fields=['is_active'])

        # Blacklist the JWT token
        try:
            from rest_framework_simplejwt.token_blacklist.models import (
                OutstandingToken, BlacklistedToken)
            token = OutstandingToken.objects.get(
                jti=session.token_jti)
            BlacklistedToken.objects.get_or_create(token=token)
        except Exception:
            pass

        return Response(
            {'message': 'Session removed successfully.'},
            status=status.HTTP_200_OK
        )


class SessionRemoveAllView(APIView):
    """Remove all sessions except current."""
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request):
        # Get current session JTI
        current_jti = ''
        try:
            from rest_framework_simplejwt.authentication import (
                JWTAuthentication)
            auth = JWTAuthentication()
            token = auth.get_validated_token(
                auth.get_raw_token(auth.get_header(request)))
            current_jti = str(token.get('jti', ''))
        except Exception:
            pass

        sessions = UserSession.objects.filter(
            user=request.user,
            is_active=True
        ).exclude(token_jti=current_jti)

        # Blacklist all tokens
        for session in sessions:
            try:
                from rest_framework_simplejwt.token_blacklist.models import (
                    OutstandingToken, BlacklistedToken)
                token = OutstandingToken.objects.get(
                    jti=session.token_jti)
                BlacklistedToken.objects.get_or_create(token=token)
            except Exception:
                pass

        sessions.update(is_active=False)

        return Response({
            'message': 'All other sessions removed.'
        })


class BecomeSellerView(APIView):
    """
    Quick promote: buyer clicks 'Become a seller' button.
    Upgrades their role and redirects to onboarding flow.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if request.user.role in ['seller', 'service_provider']:
            return Response(
                {'error': 'You are already a seller.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = BecomeSellerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(request.user)

        return Response({
            'message': 'Account upgraded to seller.',
            'next_step': 'onboarding/step-1',
        })


class SellerOnboardingStep1View(APIView):
    """Step 1 — Business details + create store."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = SellerOnboardingStep1Serializer(
            data=request.data)
        serializer.is_valid(raise_exception=True)
        store = serializer.save(request.user)

        return Response({
            'message': 'Business details saved.',
            'store_id': store.id,
            'store_slug': store.slug,
            'next_step': 'onboarding/step-2',
        })


class SellerOnboardingStep2View(APIView):
    """Step 2 — Select selling categories."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from apps.store.models import Store
        if not Store.objects.filter(user=request.user).exists():
            return Response(
                {'error': 'Please complete step 1 first.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = SellerOnboardingStep2Serializer(
            data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(request.user)

        return Response({
            'message': 'Categories saved.',
            'next_step': 'onboarding/step-3',
        })


class SellerOnboardingStep3View(APIView):
    """Step 3 — Verification docs + submit."""
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        from apps.store.models import Store
        if not Store.objects.filter(user=request.user).exists():
            return Response(
                {'error': 'Please complete steps 1 and 2 first.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = SellerOnboardingStep3Serializer(
            data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(request.user)

        # Notify admins
        try:
            from apps.accounts.tasks import (
                notify_admins_verification_request)
            from apps.accounts.models import VerificationRequest
            vr = VerificationRequest.objects.get(
                user=request.user)
            notify_admins_verification_request.delay(
                vr.id, request.user.email)
        except Exception:
            pass

        return Response({
            'message': (
                'Verification submitted. Your store setup '
                'request has been received. We will activate '
                'your store once verification is complete.'
            ),
            'next_step': 'dashboard',
        })


class OnboardingStatusView(APIView):
    """
    Returns which onboarding steps are complete.
    Used by frontend to know where to redirect.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        from apps.store.models import Store
        from apps.accounts.models import VerificationRequest

        store = Store.objects.filter(user=user).first()
        verification = VerificationRequest.objects.filter(
            user=user).first()

        steps = {
            'step_1_complete': bool(
                store and store.name and store.email),
            'step_2_complete': bool(
                store and store.categories.exists()),
            'step_3_complete': bool(verification),
            'is_verified': user.is_verified,
            'store_active': bool(
                store and store.is_active and store.is_published),
        }

        # Determine which step to go to next
        if not steps['step_1_complete']:
            steps['current_step'] = 1
        elif not steps['step_2_complete']:
            steps['current_step'] = 2
        elif not steps['step_3_complete']:
            steps['current_step'] = 3
        else:
            steps['current_step'] = None  # complete

        return Response(steps)
