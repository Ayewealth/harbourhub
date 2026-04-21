from rest_framework import serializers
from django.contrib.auth import get_user_model

from .models import Conversation, Message

User = get_user_model()


class ParticipantSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(
        source='get_full_name', read_only=True)
    store_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'full_name', 'email', 'store_name')

    def get_store_name(self, obj):
        store = getattr(obj, 'store', None)
        return store.name if store else None


class QuoteSnippetSerializer(serializers.Serializer):
    """Minimal quote data shown inside a quote message."""
    id = serializers.IntegerField()
    listing_title = serializers.CharField(
        source='listing.title')
    purchase_type = serializers.CharField()
    quantity = serializers.IntegerField()
    status = serializers.CharField()
    notes = serializers.CharField()


class MessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(
        source='sender.get_full_name', read_only=True)
    sender_id = serializers.IntegerField(
        source='sender.id', read_only=True)
    quote_data = serializers.SerializerMethodField()
    reply_to_preview = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = (
            'id',
            'conversation',
            'sender_id',
            'sender_name',
            'message_type',
            'body',
            'quote_request',
            'quote_data',
            'reply_to',
            'reply_to_preview',
            'is_read',
            'read_at',
            'created_at',
        )
        read_only_fields = (
            'id', 'conversation', 'sender_id', 'sender_name',
            'quote_data', 'reply_to_preview',
            'is_read', 'read_at', 'created_at',
        )

    def get_quote_data(self, obj):
        if obj.quote_request:
            return QuoteSnippetSerializer(obj.quote_request).data
        return None

    def get_reply_to_preview(self, obj):
        if obj.reply_to:
            return {
                'id': obj.reply_to.id,
                'sender_name': obj.reply_to.sender.get_full_name(),
                'body': obj.reply_to.body[:100],
            }
        return None


class SendMessageSerializer(serializers.Serializer):
    body = serializers.CharField(
        required=False, allow_blank=True)
    message_type = serializers.ChoiceField(
        choices=Message.MessageType.choices,
        default=Message.MessageType.TEXT
    )
    reply_to = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
        msg_type = attrs.get(
            'message_type', Message.MessageType.TEXT)
        body = attrs.get('body', '').strip()

        if msg_type == Message.MessageType.TEXT and not body:
            raise serializers.ValidationError(
                "Message body is required for text messages.")
        return attrs


class RequestQuoteInChatSerializer(serializers.Serializer):
    """
    Buyer sends a quote request from within a chat.
    Creates a QuoteRequest and a quote-type Message.
    """
    purchase_type = serializers.ChoiceField(
        choices=[('buy', 'Buy'), ('rent', 'Rent')])
    quantity = serializers.IntegerField(min_value=1, default=1)
    duration_bucket = serializers.ChoiceField(
        choices=[
            ('1_50_days', '1-50 days'),
            ('50_100_days', '50-100 days'),
            ('100_150_days', '100-150 days'),
        ],
        required=False,
        allow_blank=True
    )
    preferred_delivery_date = serializers.DateField(required=False)
    delivery_location = serializers.CharField(
        required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class RequestChangesSerializer(serializers.Serializer):
    """Buyer requests changes to a quote."""
    body = serializers.CharField()


class ConversationListSerializer(serializers.ModelSerializer):
    other_participant = serializers.SerializerMethodField()
    listing_title = serializers.CharField(
        source='listing.title', read_only=True, default=None)
    store_name = serializers.CharField(
        source='store.name', read_only=True, default=None)
    unread_count = serializers.SerializerMethodField()
    last_message_preview = serializers.CharField(read_only=True)
    last_message_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Conversation
        fields = (
            'id',
            'other_participant',
            'listing',
            'listing_title',
            'store',
            'store_name',
            'unread_count',
            'last_message_preview',
            'last_message_at',
            'created_at',
        )

    def get_other_participant(self, obj):
        request = self.context.get('request')
        if request:
            other = obj.get_other_participant(request.user)
            return ParticipantSerializer(other).data
        return None

    def get_unread_count(self, obj):
        request = self.context.get('request')
        if request:
            return obj.unread_count_for(request.user)
        return 0


class ConversationDetailSerializer(ConversationListSerializer):
    messages = MessageSerializer(many=True, read_only=True)

    class Meta(ConversationListSerializer.Meta):
        fields = ConversationListSerializer.Meta.fields + ('messages',)


class StartConversationSerializer(serializers.Serializer):
    """Start a new conversation with a vendor about a listing."""
    vendor_id = serializers.IntegerField()
    listing_id = serializers.IntegerField(required=False)
    initial_message = serializers.CharField(required=False, allow_blank=True)

    def validate_vendor_id(self, value):
        try:
            self.vendor = User.objects.get(pk=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("Vendor not found.")
        return value

    def validate_listing_id(self, value):
        if value:
            from apps.listings.models import Listing
            try:
                self.listing = Listing.objects.get(
                    pk=value, status=Listing.Status.PUBLISHED)
            except Listing.DoesNotExist:
                raise serializers.ValidationError("Listing not found.")
        return value

    def validate(self, attrs):
        request = self.context['request']
        if attrs['vendor_id'] == request.user.id:
            raise serializers.ValidationError(
                "You cannot start a conversation with yourself.")
        return attrs
