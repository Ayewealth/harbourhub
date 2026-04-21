from rest_framework import serializers
from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = (
            'id',
            'notification_type',
            'title',
            'message',
            'priority',
            'action_url',
            'action_label',
            'related_object_type',
            'related_object_id',
            'is_read',
            'read_at',
            'created_at',
        )
        read_only_fields = fields


class NotificationCountSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    unread = serializers.IntegerField()
