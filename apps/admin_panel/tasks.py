from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from .models import ReportedContent


@shared_task
def notify_admins_of_new_report(report_id):
    """Notify admins asynchronously when a new report is submitted."""
    try:
        report = ReportedContent.objects.get(pk=report_id)
        subject = f"🚨 New Content Report ({report.get_content_type_display()})"
        message = (
            f"A new content report has been submitted.\n\n"
            f"Type: {report.get_content_type_display()}\n"
            f"Reason: {report.reason}\n"
            f"Description: {report.description or 'N/A'}\n\n"
            f"Reported by: {report.reported_by.email}"
        )
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [settings.ADMIN_EMAIL],
            fail_silently=True,
        )
    except ReportedContent.DoesNotExist:
        pass


@shared_task
def send_verification_decision_email(verification_id):
    try:
        verification = VerificationRequest.objects.select_related(
            'user').get(pk=verification_id)
        subject = (
            "✅ Verification Approved" if verification.status == VerificationRequest.Status.APPROVED
            else "❌ Verification Rejected"
        )
        message = f"Hello {verification.user.first_name or verification.user.email},\n\n"
        if verification.status == VerificationRequest.Status.APPROVED:
            message += "Your verification request has been approved! 🎉"
        else:
            message += f"Your verification request has been rejected.\n\nNotes: {verification.admin_notes or 'N/A'}"
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL,
                  [verification.user.email])
    except VerificationRequest.DoesNotExist:
        pass
