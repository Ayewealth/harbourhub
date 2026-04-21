from django.db.models import Q
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone

from .models import Notification
from .serializers import NotificationSerializer, NotificationCountSerializer


class NotificationListView(generics.ListAPIView):
    """List notifications for the authenticated user."""
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['is_read', 'notification_type', 'priority']

    def get_queryset(self):
        return Notification.objects.filter(
            recipient=self.request.user
        )


class NotificationCountView(APIView):
    """Get total and unread notification counts."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        qs = Notification.objects.filter(recipient=request.user)
        return Response({
            'total': qs.count(),
            'unread': qs.filter(is_read=False).count(),
        })


class NotificationMarkReadView(APIView):
    """Mark a single notification as read."""
    permission_classes = [permissions.IsAuthenticated]

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

    def delete(self, request):
        deleted, _ = Notification.objects.filter(
            recipient=request.user
        ).delete()
        return Response(
            {'message': f'{deleted} notification(s) deleted.'},
            status=status.HTTP_204_NO_CONTENT
        )
