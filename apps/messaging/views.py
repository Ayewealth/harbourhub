import logging
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Conversation, Message
from .serializers import (
    ConversationListSerializer,
    ConversationDetailSerializer,
    SendMessageSerializer,
    StartConversationSerializer,
    RequestQuoteInChatSerializer,
    RequestChangesSerializer,
    MessageSerializer,
)

logger = logging.getLogger(__name__)


class ConversationListView(generics.ListAPIView):
    """
    List all conversations for the current user.
    Supports ?unread=true to filter unread only.
    Frontend polls this every N seconds for new conversations.
    """
    serializer_class = ConversationListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = Conversation.objects.filter(
            Q(buyer=user) | Q(vendor=user)
        ).select_related(
            'buyer', 'vendor', 'listing', 'store',
            'buyer__store', 'vendor__store'
        ).prefetch_related('messages')

        # Filter unread
        unread_only = self.request.query_params.get('unread') == 'true'
        if unread_only:
            qs = qs.filter(
                messages__is_read=False
            ).exclude(
                messages__sender=user
            ).distinct()

        return qs.order_by('-last_message_at')


class StartConversationView(APIView):
    """
    Start a new conversation or return existing one.
    Used when buyer clicks "Message vendor" or "Request quote".
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=StartConversationSerializer,
        responses={201: ConversationListSerializer, 200: ConversationListSerializer}
    )
    def post(self, request):
        serializer = StartConversationSerializer(
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)

        vendor = serializer.vendor
        listing = getattr(serializer, 'listing', None)
        initial_message = serializer.validated_data.get(
            'initial_message', '')

        # Get or create conversation
        lookup = {'buyer': request.user, 'vendor': vendor}
        if listing:
            lookup['listing'] = listing

        conversation, created = Conversation.objects.get_or_create(
            **lookup,
            defaults={
                'store': getattr(vendor, 'store', None),
            }
        )

        # Send initial message if provided
        if initial_message and created:
            msg = Message.objects.create(
                conversation=conversation,
                sender=request.user,
                message_type=Message.MessageType.TEXT,
                body=initial_message,
            )
            conversation.last_message_at = msg.created_at
            conversation.last_message_preview = initial_message[:200]
            conversation.save(update_fields=[
                'last_message_at', 'last_message_preview'])

        return Response(
            ConversationListSerializer(
                conversation, context={'request': request}
            ).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )


class ConversationDetailView(APIView):
    """
    Get a conversation with its messages.
    Frontend polls this endpoint every N seconds to get new messages.
    Marks all messages from the other party as read on fetch.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={200: ConversationDetailSerializer})
    def get(self, request, pk):
        conversation = get_object_or_404(
            Conversation,
            pk=pk
        )

        # Ensure user is a participant
        if request.user not in (
                conversation.buyer, conversation.vendor):
            return Response(
                {'error': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Mark messages from other party as read
        conversation.messages.filter(
            is_read=False
        ).exclude(
            sender=request.user
        ).update(is_read=True, read_at=timezone.now())

        # Support ?since= for polling — only return new messages
        since = request.query_params.get('since')
        messages_qs = conversation.messages.select_related(
            'sender', 'quote_request', 'quote_request__listing',
            'reply_to', 'reply_to__sender'
        )

        if since:
            messages_qs = messages_qs.filter(created_at__gt=since)

        serializer = ConversationDetailSerializer(
            conversation, context={'request': request})
        data = serializer.data
        data['messages'] = MessageSerializer(
            messages_qs, many=True).data

        return Response(data)


class SendMessageView(APIView):
    """
    Send a text or change-request message in a conversation.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=SendMessageSerializer, responses={201: MessageSerializer})
    def post(self, request, pk):
        conversation = get_object_or_404(Conversation, pk=pk)

        if request.user not in (
                conversation.buyer, conversation.vendor):
            return Response(
                {'error': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = SendMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reply_to_id = serializer.validated_data.get('reply_to')
        reply_to = None
        if reply_to_id:
            try:
                reply_to = Message.objects.get(
                    pk=reply_to_id,
                    conversation=conversation
                )
            except Message.DoesNotExist:
                pass

        msg = Message.objects.create(
            conversation=conversation,
            sender=request.user,
            message_type=serializer.validated_data.get(
                'message_type', Message.MessageType.TEXT),
            body=serializer.validated_data.get('body', ''),
            reply_to=reply_to,
        )

        # Update conversation preview
        conversation.last_message_at = msg.created_at
        conversation.last_message_preview = msg.body[:200]
        conversation.save(update_fields=[
            'last_message_at', 'last_message_preview'])

        # Fire notification
        try:
            other = conversation.get_other_participant(request.user)
            from apps.notifications.utils import create_notification
            create_notification(
                recipient=other,
                notification_type='new_message',
                title='New Message',
                message=(
                    f"{request.user.get_full_name() or request.user.email}"
                    f": {msg.body[:100]}"
                ),
                priority='medium',
                action_url=f"/messages/{conversation.id}",
                action_label="View Message",
                related_object_type='conversation',
                related_object_id=conversation.id,
            )
        except Exception:
            pass

        return Response(
            MessageSerializer(msg).data,
            status=status.HTTP_201_CREATED
        )


class RequestQuoteInChatView(APIView):
    """
    Buyer sends a quote request from within a conversation.
    Creates a QuoteRequest and attaches it as a message.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=RequestQuoteInChatSerializer, responses={201: MessageSerializer})
    def post(self, request, pk):
        conversation = get_object_or_404(
            Conversation,
            pk=pk,
            buyer=request.user  # Only buyer can request quote
        )

        if not conversation.listing:
            return Response(
                {'error': 'This conversation has no listing attached.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = RequestQuoteInChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Create QuoteRequest
        from apps.commerce.models import QuoteRequest
        quote = QuoteRequest.objects.create(
            listing=conversation.listing,
            buyer=request.user,
            store=conversation.store,
            purchase_type=serializer.validated_data['purchase_type'],
            quantity=serializer.validated_data.get('quantity', 1),
            duration_bucket=serializer.validated_data.get(
                'duration_bucket', ''),
            preferred_delivery_date=serializer.validated_data.get(
                'preferred_delivery_date'),
            delivery_location=serializer.validated_data.get(
                'delivery_location', ''),
            notes=serializer.validated_data.get('notes', ''),
        )

        # Create quote message
        msg = Message.objects.create(
            conversation=conversation,
            sender=request.user,
            message_type=Message.MessageType.QUOTE,
            body=f"Quote requested for {conversation.listing.title}",
            quote_request=quote,
        )

        # Update conversation preview
        conversation.last_message_at = msg.created_at
        conversation.last_message_preview = "Shared a quote"
        conversation.save(update_fields=[
            'last_message_at', 'last_message_preview'])

        # Notify vendor
        try:
            from apps.notifications.utils import notify_quote_received
            notify_quote_received(quote)
        except Exception:
            pass

        return Response(
            MessageSerializer(msg).data,
            status=status.HTTP_201_CREATED
        )


class RequestChangesInChatView(APIView):
    """
    Buyer requests changes to a quote from within a conversation.
    Sends a change_request message.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=RequestChangesSerializer, responses={201: MessageSerializer})
    def post(self, request, pk):
        conversation = get_object_or_404(
            Conversation,
            pk=pk,
            buyer=request.user
        )

        serializer = RequestChangesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        msg = Message.objects.create(
            conversation=conversation,
            sender=request.user,
            message_type=Message.MessageType.CHANGE_REQUEST,
            body=serializer.validated_data['body'],
        )

        conversation.last_message_at = msg.created_at
        conversation.last_message_preview = (
            f"Change request: {msg.body[:100]}")
        conversation.save(update_fields=[
            'last_message_at', 'last_message_preview'])

        # Notify vendor
        try:
            other = conversation.get_other_participant(request.user)
            from apps.notifications.utils import create_notification
            create_notification(
                recipient=other,
                notification_type='new_message',
                title='Change Request',
                message=(
                    f"{request.user.get_full_name()} "
                    f"requested changes: {msg.body[:100]}"
                ),
                priority='high',
                action_url=f"/messages/{conversation.id}",
                action_label="View Request",
                related_object_type='conversation',
                related_object_id=conversation.id,
            )
        except Exception:
            pass

        return Response(
            MessageSerializer(msg).data,
            status=status.HTTP_201_CREATED
        )


class MoveQuoteToCartFromChatView(APIView):
    """
    Buyer moves an accepted quote from chat to cart.
    Finds the quote message and calls the move-to-cart logic.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={200: dict})
    def post(self, request, pk, message_id):
        conversation = get_object_or_404(
            Conversation,
            pk=pk,
            buyer=request.user
        )

        msg = get_object_or_404(
            Message,
            pk=message_id,
            conversation=conversation,
            message_type=Message.MessageType.QUOTE,
        )

        if not msg.quote_request:
            return Response(
                {'error': 'No quote attached to this message.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        quote = msg.quote_request

        if quote.status != 'responded':
            return Response(
                {'error': 'Quote must be in responded status to move to cart.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Move to cart
        from apps.commerce.models import Cart, CartItem
        cart, _ = Cart.objects.get_or_create(buyer=request.user)

        quoted_price = request.data.get(
            'quoted_price') or quote.listing.price

        CartItem.objects.update_or_create(
            cart=cart,
            listing=quote.listing,
            purchase_type=quote.purchase_type,
            defaults={
                'quantity': quote.quantity,
                'unit_price': quoted_price,
                'store': quote.store,
            }
        )

        # Mark quote as converted
        quote.status = 'converted'
        quote.save(update_fields=['status'])

        # Send system message in chat
        system_msg = Message.objects.create(
            conversation=conversation,
            sender=request.user,
            message_type=Message.MessageType.SYSTEM,
            body="Quote accepted and moved to cart.",
        )

        conversation.last_message_at = system_msg.created_at
        conversation.last_message_preview = "You accepted this quote"
        conversation.save(update_fields=[
            'last_message_at', 'last_message_preview'])

        return Response({
            'message': 'Quote moved to cart successfully.',
            'cart_item': {
                'listing': quote.listing.title,
                'quantity': quote.quantity,
                'unit_price': str(quoted_price),
            }
        })


class UnreadMessageCountView(APIView):
    """
    Returns total unread message count.
    Used for the messages bell/badge in the nav.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={200: dict})
    def get(self, request):
        user = request.user
        unread = Message.objects.filter(
            conversation__buyer=user,
            is_read=False
        ).exclude(sender=user).count()

        unread += Message.objects.filter(
            conversation__vendor=user,
            is_read=False
        ).exclude(sender=user).count()

        return Response({'unread_count': unread})
