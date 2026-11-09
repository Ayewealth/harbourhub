# apps/accounts/social_auth.py
import logging
import requests
import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import status, permissions, serializers
from rest_framework.views import APIView
from rest_framework.response import Response
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
    """Return ``{"payload": dict|None, "error": str|None}``."""
    client_id = getattr(settings, "GOOGLE_CLIENT_ID", "")
    if not client_id:
        return {"payload": None, "error": "Google login is not configured."}

    if id_token:
        url = f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}"
    elif access_token:
        url = (
            "https://oauth2.googleapis.com/tokeninfo?access_token="
            f"{access_token}"
        )
    else:
        return {
            "payload": None,
            "error": "Either id_token or access_token is required.",
        }

    try:
        response = requests.get(url, timeout=5)
    except Exception as exc:
        logger.warning("Google token verification failed: %s", exc)
        return {"payload": None, "error": "Could not verify the Google token."}

    if response.status_code != 200:
        return {"payload": None, "error": "Invalid Google token."}

    payload = response.json()
    if payload.get("aud") != client_id:
        return {"payload": None, "error": "Invalid Google token."}
    if payload.get("iss") not in (
        "accounts.google.com", "https://accounts.google.com"
    ):
        return {"payload": None, "error": "Invalid Google token."}
    if payload.get("email_verified") not in (True, "true"):
        return {
            "payload": None,
            "error": "Google email address is not verified.",
        }
    if not payload.get("email"):
        return {
            "payload": None,
            "error": "Google token does not contain an email address.",
        }
    return {"payload": payload, "error": None}


def verify_apple_token(id_token):
    client_id = getattr(settings, "APPLE_CLIENT_ID", "")
    if not client_id:
        return {"payload": None, "error": "Apple login is not configured."}
    try:
        jwks_data = requests.get(
            "https://appleid.apple.com/auth/keys", timeout=5
        ).json()
        header = jwt.get_unverified_header(id_token)
        kid = header.get("kid")
        public_key = None
        for key in jwks_data.get("keys", []):
            if key.get("kid") == kid:
                from jwt.algorithms import RSAAlgorithm
                public_key = RSAAlgorithm.from_jwk(key)
                break
        if public_key is None:
            return {"payload": None, "error": "Invalid Apple token."}
        payload = jwt.decode(
            id_token,
            public_key,
            algorithms=["RS256"],
            audience=client_id,
            issuer="https://appleid.apple.com",
        )
        if payload.get("email_verified") not in (True, "true"):
            return {
                "payload": None,
                "error": "Apple email address is not verified.",
            }
        if not payload.get("email"):
            return {
                "payload": None,
                "error": "Apple token does not contain an email address.",
            }
        return {"payload": payload, "error": None}
    except Exception as exc:
        logger.warning("Verified Apple token decode failed: %s", exc)
        return {"payload": None, "error": "Invalid Apple token."}


def create_or_login_social_user(email, email_verified=False):
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
                is_verified=bool(email_verified),
            )
            user.set_unusable_password()
            user.save()

            # Create default UserPreference for the new user
            from apps.accounts.models import UserPreference
            UserPreference.objects.get_or_create(user=user)

        return user


class GoogleSocialLoginView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        request=inline_serializer(name='GoogleLoginRequest', fields={'id_token': serializers.CharField(required=False), 'access_token': serializers.CharField(required=False)}),
        responses={
            200: inline_serializer(
                name='GoogleLoginResponse',
                fields={
                    'refresh': serializers.CharField(),
                    'access': serializers.CharField(),
                    'user': inline_serializer(
                        name='SocialLoginUser',
                        fields={
                            'id': serializers.IntegerField(),
                            'email': serializers.EmailField(),
                            'role': serializers.CharField(),
                        },
                    ),
                },
            ),
            400: inline_serializer(name='GoogleLoginError', fields={'error': serializers.CharField()}),
            503: inline_serializer(name='GoogleLoginUnavailable', fields={'error': serializers.CharField()}),
        }
    )
    def post(self, request):
        id_token = request.data.get("id_token")
        access_token = request.data.get("access_token")

        if not id_token and not access_token:
            return Response(
                {"error": "Either id_token or access_token is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        result = verify_google_token(
            id_token=id_token, access_token=access_token
        )
        if result["error"] == "Google login is not configured.":
            return Response(
                {"error": result["error"]},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if result["payload"] is None:
            return Response(
                {"error": result["error"]},
                status=status.HTTP_400_BAD_REQUEST
            )

        payload = result["payload"]
        email = payload["email"]
        user = create_or_login_social_user(
            email, email_verified=payload.get("email_verified") in (True, "true")
        )
        tokens = get_tokens_for_user(user)
        return Response(tokens, status=status.HTTP_200_OK)


class AppleSocialLoginView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        request=inline_serializer(name='AppleLoginRequest', fields={'id_token': serializers.CharField()}),
        responses={
            200: inline_serializer(
                name='AppleLoginResponse',
                fields={
                    'refresh': serializers.CharField(),
                    'access': serializers.CharField(),
                    'user': inline_serializer(
                        name='AppleSocialLoginUser',
                        fields={
                            'id': serializers.IntegerField(),
                            'email': serializers.EmailField(),
                            'role': serializers.CharField(),
                        },
                    ),
                },
            ),
            400: inline_serializer(name='AppleLoginError', fields={'error': serializers.CharField()}),
            503: inline_serializer(name='AppleLoginUnavailable', fields={'error': serializers.CharField()}),
        }
    )
    def post(self, request):
        id_token = request.data.get("id_token")
        if not id_token:
            return Response(
                {"error": "id_token is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        result = verify_apple_token(id_token)
        if result["error"] == "Apple login is not configured.":
            return Response(
                {"error": result["error"]},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if result["payload"] is None:
            return Response(
                {"error": result["error"]},
                status=status.HTTP_400_BAD_REQUEST
            )

        payload = result["payload"]
        email = payload["email"]
        user = create_or_login_social_user(
            email, email_verified=payload.get("email_verified") in (True, "true")
        )
        tokens = get_tokens_for_user(user)
        return Response(tokens, status=status.HTTP_200_OK)
