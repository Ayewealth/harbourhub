from django.conf import settings
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import generics, permissions, status, serializers
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone

from .models import Notification, NotificationPreference, PushSubscription
from .serializers import (
    NotificationPreferenceSerializer,
    NotificationSerializer,
    PushSubscriptionSerializer,
)


class NotificationListView(generics.ListAPIView):
    """List notifications for the authenticated user."""
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['is_read', 'notification_type', 'priority']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Notification.objects.none()
        return Notification.objects.filter(
            recipient=self.request.user
        )


class NotificationCountView(APIView):
    """Get total and unread notification counts."""
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={200: inline_serializer(
        name='NotificationCountResponse',
        fields={'total': serializers.IntegerField(), 'unread': serializers.IntegerField()}
    )})
    def get(self, request):
        qs = Notification.objects.filter(recipient=request.user)
        return Response({
            'total': qs.count(),
            'unread': qs.filter(is_read=False).count(),
        })


class NotificationMarkReadView(APIView):
    """Mark a single notification as read."""
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=None, 
        responses={
            200: inline_serializer(name='NotificationMarkReadResponse', fields={'message': serializers.CharField()}),
            404: inline_serializer(name='NotificationErrorResponse', fields={'error': serializers.CharField()})
        }
    )
    def post(self, request, pk):
        try:
            notif = Notification.objects.get(
                pk=pk, recipient=request.user)
            notif.mark_as_read()
            return Response({'message': 'Notification marked as read.'})
        except Notification.DoesNotExist:
            return Response(
                {'error': 'Notification not found.'},
                status=status.HTTP_404_NOT_FOUND
            )


class NotificationMarkAllReadView(APIView):
    """Mark all notifications as read."""
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={200: inline_serializer(name='NotificationMarkAllReadResponse', fields={'message': serializers.CharField()})})
    def post(self, request):
        updated = Notification.objects.filter(
            recipient=request.user,
            is_read=False
        ).update(is_read=True, read_at=timezone.now())

        return Response({
            'message': f'{updated} notification(s) marked as read.'
        })


class NotificationDeleteView(APIView):
    """Delete a single notification."""
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        responses={
            204: inline_serializer(name='NotificationDeleteResponse', fields={'message': serializers.CharField()}),
            404: inline_serializer(name='NotificationDeleteErrorResponse', fields={'error': serializers.CharField()})
        }
    )
    def delete(self, request, pk):
        try:
            notif = Notification.objects.get(
                pk=pk, recipient=request.user)
            notif.delete()
            return Response(
                {'message': 'Notification deleted.'},
                status=status.HTTP_204_NO_CONTENT
            )
        except Notification.DoesNotExist:
            return Response(
                {'error': 'Notification not found.'},
                status=status.HTTP_404_NOT_FOUND
            )


class NotificationClearAllView(APIView):
    """Delete all notifications for the user."""
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={204: inline_serializer(name='NotificationClearAllResponse', fields={'message': serializers.CharField()})})
    def delete(self, request):
        deleted, _ = Notification.objects.filter(
            recipient=request.user
        ).delete()
        return Response(
            {'message': f'{deleted} notification(s) deleted.'},
            status=status.HTTP_204_NO_CONTENT
        )


PREFERENCE_CATEGORIES = (
    NotificationPreference.Category.TRANSACTIONAL,
    NotificationPreference.Category.MESSAGES,
    NotificationPreference.Category.MARKETING,
)


class NotificationPreferenceListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={200: NotificationPreferenceSerializer(many=True)})
    def get(self, request):
        preferences = {}
        for category in PREFERENCE_CATEGORIES:
            preference, _ = NotificationPreference.objects.get_or_create(
                user=request.user, category=category
            )
            preferences[category] = preference
        ordered = [preferences[category] for category in PREFERENCE_CATEGORIES]
        return Response(
            NotificationPreferenceSerializer(ordered, many=True).data
        )


class NotificationPreferenceDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=NotificationPreferenceSerializer,
        responses={200: NotificationPreferenceSerializer},
    )
    def patch(self, request, category):
        if category not in PREFERENCE_CATEGORIES:
            return Response(
                {"error": "Unknown notification category."},
                status=status.HTTP_404_NOT_FOUND,
            )

        preference, _ = NotificationPreference.objects.get_or_create(
            user=request.user, category=category
        )

        for field in ("in_app", "email", "sms", "push"):
            if field not in request.data:
                continue
            value = request.data[field]
            if (
                category == NotificationPreference.Category.TRANSACTIONAL
                and field in ("in_app", "email")
                and value is False
            ):
                return Response(
                    {
                        "error": (
                            "Transactional in-app and email notifications "
                            "cannot be disabled."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            setattr(preference, field, bool(value))

        preference.save()
        return Response(
            NotificationPreferenceSerializer(preference).data
        )


class PushSubscriptionListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={200: PushSubscriptionSerializer(many=True)})
    def get(self, request):
        queryset = PushSubscription.objects.filter(user=request.user)
        return Response(PushSubscriptionSerializer(queryset, many=True).data)

    @extend_schema(
        request=inline_serializer(
            name="PushSubscriptionCreate",
            fields={
                "endpoint": serializers.URLField(),
                "keys": serializers.DictField(),
                "user_agent": serializers.CharField(required=False),
            },
        ),
        responses={201: PushSubscriptionSerializer},
    )
    def post(self, request):
        endpoint = (request.data.get("endpoint") or "").strip()
        keys = request.data.get("keys") or {}
        p256dh = (keys.get("p256dh") or "").strip()
        auth = (keys.get("auth") or "").strip()
        if not endpoint or not p256dh or not auth:
            return Response(
                {"error": "endpoint, keys.p256dh and keys.auth are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing = PushSubscription.objects.filter(endpoint=endpoint).first()
        if existing is not None and existing.user_id != request.user.id:
            return Response(
                {"error": "This push subscription belongs to another account."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if existing is None:
            subscription = PushSubscription.objects.create(
                user=request.user,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                user_agent=request.data.get("user_agent", ""),
            )
            return Response(
                PushSubscriptionSerializer(subscription).data,
                status=status.HTTP_201_CREATED,
            )

        existing.p256dh = p256dh
        existing.auth = auth
        existing.user_agent = request.data.get("user_agent", existing.user_agent)
        existing.is_active = True
        existing.save()
        return Response(PushSubscriptionSerializer(existing).data)


class PushSubscriptionDeleteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request, pk):
        deleted, _ = PushSubscription.objects.filter(
            pk=pk, user=request.user
        ).delete()
        if not deleted:
            return Response(
                {"error": "Push subscription not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class PushPublicKeyView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        responses={200: inline_serializer(
            name="PushPublicKeyResponse",
            fields={
                "public_key": serializers.CharField(),
                "configured": serializers.BooleanField(),
            },
        )}
    )
    def get(self, request):
        public_key = getattr(settings, "VAPID_PUBLIC_KEY", "")
        return Response({
            "public_key": public_key,
            "configured": bool(public_key),
        })
