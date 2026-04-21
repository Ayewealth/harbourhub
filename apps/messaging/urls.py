from django.urls import path
from .views import (
    ConversationListView,
    StartConversationView,
    ConversationDetailView,
    SendMessageView,
    RequestQuoteInChatView,
    RequestChangesInChatView,
    MoveQuoteToCartFromChatView,
    UnreadMessageCountView,
)

urlpatterns = [
    # Conversations
    path('', ConversationListView.as_view(),
         name='conversation-list'),
    path('start/', StartConversationView.as_view(),
         name='conversation-start'),
    path('<int:pk>/', ConversationDetailView.as_view(),
         name='conversation-detail'),

    # Messages
    path('<int:pk>/send/', SendMessageView.as_view(),
         name='message-send'),
    path('<int:pk>/request-quote/', RequestQuoteInChatView.as_view(),
         name='message-request-quote'),
    path('<int:pk>/request-changes/', RequestChangesInChatView.as_view(),
         name='message-request-changes'),
    path('<int:pk>/messages/<int:message_id>/move-to-cart/',
         MoveQuoteToCartFromChatView.as_view(),
         name='message-move-to-cart'),

    # Counts
    path('unread/', UnreadMessageCountView.as_view(),
         name='message-unread-count'),
]
