from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.contrib import messages

from .models import ReportedContent, AdminActionLog


@admin.register(ReportedContent)
class ReportedContentAdmin(admin.ModelAdmin):
    """Admin configuration for user-reported content"""

    list_display = (
        'id', 'content_type_display', 'object_id',
        'reason', 'status', 'reported_by',
        'created_at', 'reviewed_by', 'reviewed_at',
    )
    list_filter = (
        'status', 'reason', 'content_type',
        ('created_at', admin.DateFieldListFilter),
        ('reviewed_at', admin.DateFieldListFilter),
    )
    search_fields = (
        'reason', 'description',
        'reported_by__email', 'reviewed_by__email',
    )
    readonly_fields = (
        'reported_by', 'created_at',
        'reviewed_at', 'content_link',
    )
    ordering = ['-created_at']
    date_hierarchy = 'created_at'
    actions = ['mark_as_resolved', 'mark_as_dismissed']

    fieldsets = (
        (_('Reported Content'), {
            'fields': (
                'content_type', 'object_id', 'content_link',
                'reason', 'description'
            )
        }),
        (_('Reporting Info'), {
            'fields': (
                'reported_by', 'status',
                'reviewed_by', 'admin_notes',
                'created_at', 'reviewed_at'
            )
        }),
    )

    # ------------------------
    # DISPLAY HELPERS
    # ------------------------

    def content_type_display(self, obj):
        """Display content type in a readable format"""
        return obj.content_type.model.capitalize() if obj.content_type else '-'
    content_type_display.short_description = _("Content Type")

    def content_link(self, obj):
        """Provide a direct link to the reported object in admin if available"""
        if not obj.content_type or not obj.object_id:
            return "-"
        model_class = obj.content_type.model_class()
        try:
            related_obj = model_class.objects.get(pk=obj.object_id)
        except model_class.DoesNotExist:
            return _("Object deleted")

        admin_url = f"/admin/{obj.content_type.app_label}/{obj.content_type.model}/{obj.object_id}/change/"
        return format_html('<a href="{}">{}</a>', admin_url, str(related_obj))
    content_link.short_description = _("Reported Object")

    def get_queryset(self, request):
        """Optimize queryset"""
        qs = super().get_queryset(request)
        return qs.select_related('reported_by', 'reviewed_by', 'content_type')

    # ------------------------
    # ADMIN ACTIONS
    # ------------------------

    @admin.action(description=_("Mark selected reports as resolved"))
    def mark_as_resolved(self, request, queryset):
        """Bulk mark reports as resolved"""
        count = 0
        for report in queryset.filter(status=ReportedContent.Status.PENDING):
            report.status = ReportedContent.Status.RESOLVED
            report.reviewed_by = request.user
            report.mark_as_reviewed(
                admin_user=request.user,
                notes="Bulk action: marked as resolved via admin"
            )
            AdminActionLog.log_action(
                admin_user=request.user,
                action_type=AdminActionLog.ActionType.CONTENT_REVIEWED,
                description=f"Resolved reported content ID {report.id}",
                content_object=report,
                extra_data={'status': report.status}
            )
            count += 1
        self.message_user(
            request,
            _(f"{count} report(s) marked as resolved successfully."),
            messages.SUCCESS
        )

    @admin.action(description=_("Dismiss selected reports as invalid"))
    def mark_as_dismissed(self, request, queryset):
        """Bulk dismiss reports"""
        count = 0
        for report in queryset.exclude(status__in=[ReportedContent.Status.DISMISSED, ReportedContent.Status.RESOLVED]):
            report.status = ReportedContent.Status.DISMISSED
            report.reviewed_by = request.user
            report.mark_as_reviewed(
                admin_user=request.user,
                notes="Bulk action: dismissed as invalid via admin"
            )
            AdminActionLog.log_action(
                admin_user=request.user,
                action_type=AdminActionLog.ActionType.CONTENT_REVIEWED,
                description=f"Dismissed reported content ID {report.id}",
                content_object=report,
                extra_data={'status': report.status}
            )
            count += 1
        self.message_user(
            request,
            _(f"{count} report(s) dismissed successfully."),
            messages.WARNING
        )


@admin.register(AdminActionLog)
class AdminActionLogAdmin(admin.ModelAdmin):
    """Admin configuration for audit logs"""

    list_display = (
        'id', 'admin_user', 'action_type',
        'description_short', 'timestamp',
    )
    list_filter = ('action_type', ('timestamp', admin.DateFieldListFilter))
    search_fields = ('admin_user__email', 'description')
    readonly_fields = ('admin_user', 'action_type', 'description',
                       'extra_data', 'timestamp')
    ordering = ['-timestamp']
    date_hierarchy = 'timestamp'

    def description_short(self, obj):
        """Shorten description for list display"""
        return (obj.description[:75] + '...') if len(obj.description) > 75 else obj.description
    description_short.short_description = _("Description")

    def has_add_permission(self, request):
        """Prevent manual creation of logs"""
        return False

    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of logs"""
        return False
