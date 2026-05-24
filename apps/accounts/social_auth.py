# apps/accounts/social_auth.py
import logging
import requests
import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from rest_framework_simplejwt.tokens import RefreshToken

logger = logging.getLogger(__name__)
User = get_user_model()

def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'user': {
            'id': user.id,
            'email': user.email,
            'role': user.role,
        }
    }

def verify_google_token(id_token=None, access_token=None):
    if id_token:
        url = f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}"
    elif access_token:
        url = f"https://oauth2.googleapis.com/tokeninfo?access_token={access_token}"
    else:
        return None

    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception as exc:
        logger.warning("Google token verification failed: %s", exc)
    return None

def verify_apple_token(id_token):
    # In DEBUG mode, skip signature verification
    if getattr(settings, "DEBUG", True):
        try:
            return jwt.decode(id_token, options={"verify_signature": False})
        except Exception as exc:
            logger.warning("Unverified Apple token decode failed: %s", exc)
            return None

    # In production, verify against Apple's JWKs
    try:
        jwks_url = "https://appleid.apple.com/auth/keys"
        jwks_data = requests.get(jwks_url, timeout=5).json()
        unverified_header = jwt.get_unverified_header(id_token)
        kid = unverified_header.get("kid")

        public_key = None
        for key in jwks_data.get("keys", []):
            if key.get("kid") == kid:
                from jwt.algorithms import RSAAlgorithm
                public_key = RSAAlgorithm.from_jwk(key)
                break

        if not public_key:
            return None

        return jwt.decode(
            id_token,
            public_key,
            algorithms=["RS256"],
            options={"verify_aud": False}
        )
    except Exception as exc:
        logger.warning("Verified Apple token decode failed: %s", exc)
    return None

def create_or_login_social_user(email):
    with transaction.atomic():
        try:
            user = User.objects.get(email=email)
            logger.info("Social login for existing user: %s", email)
        except User.DoesNotExist:
            logger.info("Social login: Auto-creating user: %s", email)
            username = email.split("@")[0]
            # Ensure unique username
            base_username = username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1

            user = User.objects.create(
                email=email,
                username=username,
                role=User.Role.BUYER,
                is_verified=True,
            )
            user.set_unusable_password()
            user.save()

            # Create default UserPreference for the new user
            from apps.accounts.models import UserPreference
            UserPreference.objects.get_or_create(user=user)

        return user


class GoogleSocialLoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        id_token = request.data.get("id_token")
        access_token = request.data.get("access_token")

        if not id_token and not access_token:
            return Response(
                {"error": "Either id_token or access_token is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        payload = verify_google_token(id_token=id_token, access_token=access_token)
        if not payload:
            return Response(
                {"error": "Invalid Google token."},
                status=status.HTTP_400_BAD_REQUEST
            )

        email = payload.get("email")
        if not email:
            return Response(
                {"error": "Google token does not contain an email address."},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = create_or_login_social_user(email)
        tokens = get_tokens_for_user(user)
        return Response(tokens, status=status.HTTP_200_OK)


class AppleSocialLoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        id_token = request.data.get("id_token")
        if not id_token:
            return Response(
                {"error": "id_token is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        payload = verify_apple_token(id_token)
        if not payload:
            return Response(
                {"error": "Invalid Apple token."},
                status=status.HTTP_400_BAD_REQUEST
            )

        email = payload.get("email")
        if not email:
            # Fallback if Apple email is not in payload, check subject or format a dummy/placeholder if needed
            # but let's raise error since email is required by User model
            return Response(
                {"error": "Apple token does not contain an email address."},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = create_or_login_social_user(email)
        tokens = get_tokens_for_user(user)
        return Response(tokens, status=status.HTTP_200_OK)
