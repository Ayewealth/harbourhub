# apps/inquiries/views.py
from django.db.models import Q
from django.urls import reverse
from django.conf import settings
from django.db import transaction

from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django_ratelimit.decorators import ratelimit
from django.utils.decorators import method_decorator
from drf_spectacular.utils import extend_schema, extend_schema_view

from .models import Inquiry
from .serializers import (
    InquirySerializer, InquiryCreateSerializer,
    InquiryListSerializer, InquiryReplySerializer
)
from .permissions import IsInquiryParticipant


@extend_schema_view(
    list=extend_schema(
        summary="List inquiries",
        description="Get user's sent and received inquiries"
    ),
    create=extend_schema(
        summary="Create inquiry",
        description="Send inquiry about a listing"
    ),
    retrieve=extend_schema(
        summary="Get inquiry details",
        description="Get detailed information about an inquiry"
    )
)
class InquiryViewSet(viewsets.ModelViewSet):
    """CRUD operations for inquiries"""

    serializer_class = InquirySerializer
    permission_classes = [permissions.IsAuthenticated, IsInquiryParticipant]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['status', 'listing__category']
    http_method_names = ['get', 'post', 'patch', 'delete']

    def get_queryset(self):
        """Get inquiries for current user"""
        if getattr(self, "swagger_fake_view", False):
            return Inquiry.objects.none()

        user = self.request.user
        return Inquiry.objects.filter(
            Q(from_user=user) | Q(to_user=user)
        ).select_related('listing', 'from_user', 'to_user').order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'create':
            return InquiryCreateSerializer
        elif self.action == 'list':
            return InquiryListSerializer
        elif self.action == 'reply':
            return InquiryReplySerializer
        return InquirySerializer

    @method_decorator(ratelimit(key='user', rate='10/h', method='POST'))
    def create(self, request, *args, **kwargs):
        """
        Create inquiry with rate limiting.
        Accepts multipart file uploads via field name `attachments` (multiple).
        The serializer also supports `attachments_data` list field; we'll pass files into save()
        so the serializer create() can use them.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # collect attachments from multipart file uploads if present
        attachments = request.FILES.getlist(
            'attachments') if request.FILES else []
        # Save with attachments_data passed as kwarg so serializer.create receives them
        with transaction.atomic():
            inquiry = serializer.save(attachments_data=attachments)

        out_serializer = InquirySerializer(
            inquiry, context=self.get_serializer_context())
        return Response(out_serializer.data, status=status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        """Get inquiry details and mark as read"""
        instance = self.get_object()

        # Mark as read if user is the recipient
        if instance.to_user == request.user and not instance.is_read:
            instance.mark_as_read()

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @extend_schema(
        summary="Get sent inquiries",
        description="Get inquiries sent by current user"
    )
    @action(detail=False, methods=['get'])
    def sent(self, request):
        """Get sent inquiries"""
        queryset = self.get_queryset().filter(from_user=request.user)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @extend_schema(
        summary="Get received inquiries",
        description="Get inquiries received by current user"
    )
    @action(detail=False, methods=['get'])
    def received(self, request):
        """Get received inquiries"""
        queryset = self.get_queryset().filter(to_user=request.user)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @extend_schema(
        summary="Reply to inquiry",
        description="Reply to an inquiry"
    )
    @action(detail=True, methods=['post'])
    def reply(self, request, pk=None):
        """Reply to an inquiry"""
        inquiry = self.get_object()

        # Only recipient can reply
        if inquiry.to_user != request.user:
            return Response({
                'error': 'Only inquiry recipient can reply'
            }, status=status.HTTP_403_FORBIDDEN)

        # pass `inquiry` into serializer context so serializer.create() can use it
        serializer_context = {
            **self.get_serializer_context(), "inquiry": inquiry}
        serializer = self.get_serializer(
            data=request.data, context=serializer_context)
        serializer.is_valid(raise_exception=True)
        # serializer.create uses context['inquiry'] and request.user
        reply = serializer.save()

        return Response({
            'message': 'Reply sent successfully',
            'reply_id': getattr(reply, 'id', None)
        }, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Mark inquiry as spam",
        description="Mark inquiry as spam"
    )
    @action(detail=True, methods=['post'])
    def mark_spam(self, request, pk=None):
        """Mark inquiry as spam"""
        inquiry = self.get_object()

        # Only recipient can mark as spam
        if inquiry.to_user != request.user:
            return Response({
                'error': 'Only inquiry recipient can mark as spam'
            }, status=status.HTTP_403_FORBIDDEN)

        inquiry.status = Inquiry.Status.SPAM
        inquiry.save(update_fields=['status'])

        return Response({
            'message': 'Inquiry marked as spam'
        }, status=status.HTTP_200_OK)
