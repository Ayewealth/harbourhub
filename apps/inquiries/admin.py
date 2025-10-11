# apps/inquiries/admin.py
from django.contrib import admin
from .models import Inquiry, InquiryReply, InquiryAttachment


@admin.register(Inquiry)
class InquiryAdmin(admin.ModelAdmin):
    list_display = ('id', 'listing', 'from_user', 'to_user',
                    'subject', 'status', 'is_urgent', 'created_at')
    search_fields = ('subject', 'message', 'contact_email', 'contact_name')
    list_filter = ('status', 'is_urgent', 'created_at')
    readonly_fields = ('created_at', 'read_at', 'replied_at',
                       'ip_address', 'user_agent')


@admin.register(InquiryReply)
class InquiryReplyAdmin(admin.ModelAdmin):
    list_display = ('id', 'inquiry', 'user', 'created_at')
    search_fields = ('message',)


@admin.register(InquiryAttachment)
class InquiryAttachmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'inquiry', 'original_name',
                    'file_size', 'created_at')
    readonly_fields = ('original_name', 'file_size',
                       'content_type', 'created_at')
