from rest_framework import serializers
from .models import Notification, NotificationPreference, PushSubscription


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


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = ("category", "in_app", "email", "sms", "push")
        read_only_fields = ("category",)


class PushSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PushSubscription
        fields = (
            "id", "endpoint", "user_agent", "is_active",
            "created_at", "updated_at",
        )
        read_only_fields = fields
