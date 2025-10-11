# apps/inquiries/serializers.py
from rest_framework import serializers
from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model

from apps.listings.models import Listing
from .models import Inquiry, InquiryReply, InquiryAttachment

User = get_user_model()

# File limits - keep consistent with your .env settings
MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024  # 25 MB
ALLOWED_ATTACHMENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "text/plain",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class InquiryAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = InquiryAttachment
        fields = ("id", "file", "original_name",
                  "file_size", "content_type", "created_at")
        read_only_fields = ("original_name", "file_size",
                            "content_type", "created_at")

    def validate_file(self, value):
        if value.size > MAX_ATTACHMENT_SIZE:
            raise serializers.ValidationError(
                "Attachment too large (max 25MB).")
        content_type = getattr(value, "content_type", None)
        if content_type and content_type not in ALLOWED_ATTACHMENT_TYPES:
            raise serializers.ValidationError("Unsupported attachment type.")
        return value


class InquiryListSerializer(serializers.ModelSerializer):
    listing_title = serializers.CharField(
        source="listing.title", read_only=True)
    from_user_name = serializers.CharField(
        source="from_user.get_full_name", read_only=True)
    to_user_name = serializers.CharField(
        source="to_user.get_full_name", read_only=True)
    attachments_count = serializers.SerializerMethodField()

    class Meta:
        model = Inquiry
        fields = (
            "id", "listing", "listing_title",
            "from_user", "from_user_name", "to_user", "to_user_name",
            "subject", "status", "is_urgent", "created_at", "attachments_count"
        )

    def get_attachments_count(self, obj):
        return obj.attachments.count()


class InquirySerializer(serializers.ModelSerializer):
    """Detailed serializer for retrieve view"""
    listing_title = serializers.CharField(
        source="listing.title", read_only=True)
    replies = serializers.SerializerMethodField()
    attachments = InquiryAttachmentSerializer(many=True, read_only=True)
    from_user_name = serializers.CharField(
        source="from_user.get_full_name", read_only=True)
    to_user_name = serializers.CharField(
        source="to_user.get_full_name", read_only=True)

    class Meta:
        model = Inquiry
        fields = (
            "id", "listing", "listing_title",
            "from_user", "from_user_name", "to_user", "to_user_name",
            "subject", "message", "contact_name", "contact_email", "contact_phone", "contact_company",
            "status", "is_urgent", "read_at", "replied_at", "created_at",
            "attachments", "replies", "ip_address", "user_agent"
        )
        read_only_fields = ("from_user", "to_user", "status",
                            "read_at", "replied_at", "created_at")

    def get_replies(self, obj):
        return InquiryReplySerializer(obj.replies.all(), many=True).data


class InquiryCreateSerializer(serializers.ModelSerializer):
    """
    Create serializer: accepts attachments_data as list of files.
    'from_user' will be set from request.user automatically in view.
    """
    attachments_data = serializers.ListField(
        child=serializers.FileField(),
        write_only=True,
        required=False,
        allow_empty=True
    )

    class Meta:
        model = Inquiry
        fields = (
            "listing",
            "subject", "message",
            "contact_name", "contact_email", "contact_phone", "contact_company",
            "is_urgent", "attachments_data",
        )

    def validate_listing(self, value):
        # ensure listing exists and is published (optional business rule)
        if not value:
            raise serializers.ValidationError("Listing must be provided.")
        if value.status != Listing.Status.PUBLISHED:
            # optionally allow inquiries to drafts for owners / test, but default block
            raise serializers.ValidationError(
                "Cannot send inquiry for an unpublished listing.")
        # prevent self-inquiry
        request = self.context.get("request")
        if request and request.user.is_authenticated and value.user_id == request.user.id:
            raise serializers.ValidationError(
                "You cannot send an inquiry to your own listing.")
        return value

    def validate(self, attrs):
        # Basic contact email normalization
        attrs['contact_email'] = attrs.get('contact_email', '').strip().lower()
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        attachments = validated_data.pop("attachments_data", [])
        request = self.context.get("request")
        from_user = request.user if request else None

        # set to_user from listing owner
        listing = validated_data.get("listing")
        to_user = listing.user

        inquiry = Inquiry.objects.create(
            listing=listing,
            from_user=from_user,
            to_user=to_user,
            subject=validated_data.get("subject"),
            message=validated_data.get("message"),
            contact_name=validated_data.get("contact_name"),
            contact_email=validated_data.get("contact_email"),
            contact_phone=validated_data.get("contact_phone", ""),
            contact_company=validated_data.get("contact_company", ""),
            is_urgent=validated_data.get("is_urgent", False),
            ip_address=request.META.get("HTTP_X_FORWARDED_FOR", request.META.get(
                "REMOTE_ADDR")) if request else None,
            user_agent=request.META.get(
                "HTTP_USER_AGENT", "") if request else "",
        )

        # create attachments
        for f in attachments:
            att = InquiryAttachment(file=f)
            att.inquiry = inquiry
            # save will populate original_name and file_size
            att.save()

        # trigger a task to notify owner (if you have celery task)
        try:
            from apps.inquiries.tasks import send_inquiry_notification_task
            send_inquiry_notification_task.delay(inquiry.id)
        except Exception:
            # don't break on missing task; just continue
            pass

        return inquiry


class InquiryReplySerializer(serializers.ModelSerializer):
    class Meta:
        model = InquiryReply
        fields = ("id", "inquiry", "user", "message", "created_at")
        read_only_fields = ("id", "user", "inquiry", "created_at")

    def validate(self, attrs):
        request = self.context.get("request")
        # view sets this in serializer context
        inquiry = self.context.get("inquiry")
        if not inquiry:
            raise serializers.ValidationError("Inquiry context missing.")
        # only recipient can reply (per your view logic)
        if request and request.user != inquiry.to_user:
            raise serializers.ValidationError(
                "Only the listing owner may reply to this inquiry.")
        return attrs

    def create(self, validated_data):
        inquiry = self.context.get("inquiry")
        user = self.context["request"].user
        reply = InquiryReply.objects.create(
            inquiry=inquiry, user=user, message=validated_data["message"])
        # task to notify inquirer
        try:
            from apps.inquiries.tasks import send_reply_notification_task
            send_reply_notification_task.delay(reply.id)
        except Exception:
            pass
        return reply
