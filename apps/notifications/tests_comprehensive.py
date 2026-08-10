from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from django.contrib.auth import get_user_model
from apps.notifications.models import Notification

User = get_user_model()

class NotificationEdgeCaseTests(APITestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(
            email="user1@notif.com", username="user1", password="testpassword123"
        )
        self.user2 = User.objects.create_user(
            email="user2@notif.com", username="user2", password="testpassword123"
        )
        
        self.notif1 = Notification.objects.create(
            recipient=self.user1,
            notification_type=Notification.NotificationType.NEW_MESSAGE,
            title="Message 1",
            message="Body 1"
        )
        self.notif2 = Notification.objects.create(
            recipient=self.user2,
            notification_type=Notification.NotificationType.NEW_MESSAGE,
            title="Message 2",
            message="Body 2"
        )
        
        self.client.force_authenticate(user=self.user1)

    def test_mark_other_user_notification_read(self):
        """Test that a user cannot mark another user's notification as read."""
        url = reverse('notification-mark-read', args=[self.notif2.id])
        response = self.client.post(url, format='json')
        
        # User 1 trying to mark User 2's notification should 404 or 403
        self.assertIn(response.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN])
        
        self.notif2.refresh_from_db()
        self.assertFalse(self.notif2.is_read)

    def test_mark_all_read_isolation(self):
        """Test mark all read only affects the authenticated user's notifications."""
        url = reverse('notification-mark-all-read')
        response = self.client.post(url, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.notif1.refresh_from_db()
        self.notif2.refresh_from_db()
        
        self.assertTrue(self.notif1.is_read)
        self.assertFalse(self.notif2.is_read)
